#!/usr/bin/env python3
"""Command Code model-metadata sync / drift-check.

Faithful Python port of the reference pi plugin's
``.github/scripts/check-commandcode-model-metadata.ts``.

The Command Code Provider API's ``/models`` endpoint returns only
``id``/``name``/``context_length``. Reasoning capability, selectable reasoning
efforts, image input, and per-model output caps live in the `command-code` npm
CLI package, in two bundled files:

    dist/bundled/command-code-knowledge/reference/models.md
    dist/cli.mjs

This script downloads the latest ``command-code`` tarball, parses those two
files, and compares the derived metadata against the checked-in
``catalog.py`` snapshot. Run with ``--write`` to regenerate ``catalog.py``.

Usage:
    python sync_catalog.py                    # report only; exit 1 on drift
    python sync_catalog.py --write            # regenerate catalog.py (and README)
    python sync_catalog.py command-code@1.47.0 --write
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from shutil import which
from typing import Optional

# ── Paths (repo-relative) ────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "plugins" / "model-providers" / "commandcode" / "catalog.py"
README_PATH = REPO_ROOT / "README.md"

MODELS_REFERENCE_PATH = "dist/bundled/command-code-knowledge/reference/models.md"
CLI_BUNDLE_PATH = "dist/cli.mjs"

# Effort values seen in models.md so far. This is a *known* vocabulary, not a
# gate: upstream adds levels over time (``off`` arrived with the DeepSeek V4
# family), and a new well-formed level is drift — exit 1, draft PR — never "the
# check could not run" (exit 2, red job). A value outside this set is carried
# into the snapshot and called out in the report instead of failing the parse.
KNOWN_EFFORTS = frozenset({"off", "minimal", "low", "medium", "high", "xhigh", "max"})

# models.md spells every effort value as a bare lowercase token. This shape check
# is the only hard gate, and it is what separates "upstream added a level" (data
# drift) from "the table format changed under us" (cannot run).
_EFFORT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# npm package spec accepted on the command line: letters, digits and the
# characters npm allows in name/scope/tag/version. The spec arrives unquoted
# from a workflow dispatch input and reaches a shell command line on Windows,
# so it is validated rather than trusted.
_PACKAGE_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@/._+-]*$")


def _validate_package_spec(package_spec: str) -> str:
    """Return the trimmed spec, or raise when it is not a plain npm spec."""
    spec = (package_spec or "").strip()
    if not _PACKAGE_SPEC_RE.match(spec):
        raise ValueError(f"Invalid Command Code package spec: {package_spec!r}")
    return spec


# ── Data model (matches TS CommandCodeModelMetadata) ─────────────────────────


class ModelMetadata:
    def __init__(
        self,
        image_model_ids: list[str],
        reasoning_model_ids: list[str],
        reasoning_efforts: dict[str, list[str]],
        max_output_tokens: dict[str, int],
        cli_version: str = "",
        unrecognized_efforts: Optional[list[str]] = None,
    ):
        self.image_model_ids = image_model_ids
        self.reasoning_model_ids = reasoning_model_ids
        self.reasoning_efforts = reasoning_efforts
        self.max_output_tokens = max_output_tokens
        self.cli_version = cli_version
        # Well-formed effort values this project has not seen before; they are
        # kept, and the report flags them for review.
        self.unrecognized_efforts = list(unrecognized_efforts or [])


def _sorted(values) -> list[str]:
    return sorted(set(values))


# ── Parser: models.md ────────────────────────────────────────────────────────
_MODELS_ROW_RE = re.compile(r"^\| `([^`]+)` \| [^|]* \| [^|]* \| ([^|]*) \|")


def parse_models_reference(markdown: str):
    model_ids = set()
    reasoning_efforts: dict[str, list[str]] = {}
    unrecognized_efforts: set[str] = set()

    for line in markdown.split("\n"):
        match = _MODELS_ROW_RE.match(line)
        if not match:
            continue
        model_id = match.group(1)
        efforts_column = match.group(2).strip()
        if not model_id or not efforts_column:
            raise ValueError(f"Could not parse model row: {line}")

        if efforts_column == "—":  # em-dash → no selectable efforts
            efforts: Optional[list[str]] = None
        else:
            efforts = [e.strip() for e in efforts_column.split(",")]
            if not efforts or any(not _EFFORT_TOKEN_RE.match(e) for e in efforts):
                raise ValueError(
                    f"Unexpected reasoning efforts for {model_id}: {efforts_column}"
                )

        if model_id in model_ids:
            # The reference splits the catalog into one table per vendor, so a
            # row can legitimately repeat. A repeat that agrees with itself is
            # the same metadata twice; one that disagrees is ambiguous, so it
            # still fails loudly rather than picking a winner.
            if reasoning_efforts.get(model_id) != efforts:
                raise ValueError(
                    f"Conflicting reasoning efforts for {model_id}: "
                    f"{reasoning_efforts.get(model_id) or '—'} vs {efforts_column}"
                )
            continue
        model_ids.add(model_id)

        if efforts is None:
            continue
        unrecognized_efforts.update(e for e in efforts if e not in KNOWN_EFFORTS)
        reasoning_efforts[model_id] = efforts

    if not model_ids:
        raise ValueError("No model rows found in Command Code reference")

    return {
        "model_ids": _sorted(model_ids),
        "reasoning_efforts": dict(sorted(reasoning_efforts.items())),
        "unrecognized_efforts": sorted(unrecognized_efforts),
    }


# ── Parser: cli.mjs ──────────────────────────────────────────────────────────
#
# Upstream ships the catalog as minified JS object literals inside dist/cli.mjs.
# This parser used to key on exact source text, and two of those anchors died in
# command-code@1.82.3 without changing anything semantically:
#
#   * a `new Set([...text-only ids...])` next to
#     `__name(isKnownTextOnlyModel,"isKnownTextOnlyModel")` — deleted, so
#     `rfind("new Set([")` landed on an unrelated `new Set(["anthropic",
#     "openai"])` and `json.loads` failed with "Extra data: line 1 column 23",
#   * `{id:"<id>",inputModalities:` as the object opener — invalidated the same
#     release, when the objects were re-serialized as `display:{...},id:"<id>",
#     inputModalities:...`.
#
# Both surfaced as exit 2 ("the check could not run"), i.e. a red scheduled job
# that never opens the drift PR the pipeline exists for. The lesson is that
# nothing here may depend on field order, on a neighbouring declaration, or on
# brace matching — the bundle contains regex and template literals that defeat
# naive scanners, and it is re-minified on every release.
#
# What upstream *does* keep stable is the shape of a catalog model object: it
# carries its own `id:"..."` and an `inputModalities:[...]` array. So anchor on
# the id, treat the text up to the next `id:"` as that model's own fields, and
# read each field independently.

_ID_ANCHOR_RE = re.compile(r'id:"')
_INPUT_MODALITIES_RE = re.compile(r"inputModalities:\[([^\]]*)\]")
_MAX_OUTPUT_RE = re.compile(r"maxOutputTokens:(null|[0-9][0-9.e+]*)")
_REASONING_FLAG_RE = re.compile(r"reasoning:(!0|!1)")
_REASONING_EFFORTS_RE = re.compile(r"reasoningEfforts:(null|\[)")

# Guard for the final model in the bundle, which has no following `id:"` to
# bound its fields. Every field this parser reads sits immediately after the id.
_FIELD_WINDOW = 1200


def _model_field_windows(bundle: str, model_id: str) -> list[str]:
    """Return the field text of every object literal declaring *model_id*.

    A model's own fields are the text between its ``id:"..."`` and the next
    ``id:"..."`` in the bundle. Upstream lists each model more than once (the
    served catalog and the embedded catalog), so this returns one window per
    listing; callers merge them.
    """
    needle = f'id:"{model_id}"'
    windows = []
    index = 0
    while True:
        start = bundle.find(needle, index)
        if start < 0:
            return windows
        following = _ID_ANCHOR_RE.search(bundle, start + len(needle))
        end = following.start() if following else start + _FIELD_WINDOW
        windows.append(bundle[start:end])
        index = start + len(needle)


def parse_bundle_model_capabilities(bundle: str, model_ids: list[str]):
    """Derive image support, reasoning support and output caps from the bundle."""
    image_model_ids = []
    reasoning_model_ids = []
    max_output_tokens: dict[str, int] = {}

    for model_id in model_ids:
        windows = _model_field_windows(bundle, model_id)
        if not windows:
            raise ValueError(
                f"Could not find model metadata for {model_id} in the Command Code bundle "
                "(the bundle format may have changed again)"
            )

        declared = set()
        for window in windows:
            modalities = _INPUT_MODALITIES_RE.search(window)
            if modalities:
                declared.add(tuple(re.findall(r'"([^"]*)"', modalities.group(1))))
        if not declared:
            raise ValueError(f"Could not find input modalities for {model_id}")
        if len(declared) > 1:
            raise ValueError(
                f"Conflicting input modalities for {model_id}: {[list(d) for d in sorted(declared)]}"
            )
        if "image" in next(iter(declared)):
            image_model_ids.append(model_id)

        is_reasoning = False
        for window in windows:
            flag = _REASONING_FLAG_RE.search(window)
            efforts = _REASONING_EFFORTS_RE.search(window)
            if (flag and flag.group(1) == "!0") or (efforts and efforts.group(1) == "["):
                is_reasoning = True

            max_output = _MAX_OUTPUT_RE.search(window)
            if max_output and max_output.group(1) != "null":
                value = float(max_output.group(1))
                if not (value > 0 and value == int(value)):
                    raise ValueError(
                        f"Unexpected max output tokens for {model_id}: {max_output.group(1)}"
                    )
                previous = max_output_tokens.get(model_id)
                if previous is not None and previous != int(value):
                    raise ValueError(
                        f"Conflicting max output tokens for {model_id}: {previous} vs {int(value)}"
                    )
                max_output_tokens[model_id] = int(value)
        if is_reasoning:
            reasoning_model_ids.append(model_id)

    return {
        "image_model_ids": _sorted(image_model_ids),
        "reasoning_model_ids": _sorted(reasoning_model_ids),
        "max_output_tokens": dict(sorted(max_output_tokens.items())),
    }


def command_code_model_metadata_from_contents(
    models_reference: str, cli_bundle: str
) -> ModelMetadata:
    reference = parse_models_reference(models_reference)
    capabilities = parse_bundle_model_capabilities(cli_bundle, reference["model_ids"])

    return ModelMetadata(
        image_model_ids=capabilities["image_model_ids"],
        reasoning_model_ids=capabilities["reasoning_model_ids"],
        reasoning_efforts=reference["reasoning_efforts"],
        max_output_tokens=capabilities["max_output_tokens"],
        unrecognized_efforts=reference["unrecognized_efforts"],
    )


# ── Current snapshot (from catalog.py) ───────────────────────────────────────


def import_current_metadata() -> ModelMetadata:
    """Import the catalog's static tables directly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_cc_catalog", str(CATALOG_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return ModelMetadata(
        image_model_ids=_sorted(mod.MODEL_INPUT_MODALITIES.keys()),
        reasoning_model_ids=_sorted(mod.MODEL_REASONING),
        reasoning_efforts={
            k: list(v) for k, v in sorted(mod.MODEL_EFFORTS.items())
        },
        max_output_tokens=dict(sorted(mod.MODEL_MAX_OUTPUT_TOKENS.items())),
        cli_version=mod.COMMAND_CODE_CLI_VERSION,
    )


# ── diff ─────────────────────────────────────────────────────────────────────


class ModelMetadataDiff:
    def __init__(self, current, upstream, current_version, upstream_version):
        self.version_changed = current_version != upstream_version
        self.current = current
        self.upstream = upstream
        cur_img = set(current.image_model_ids)
        up_img = set(upstream.image_model_ids)
        cur_reas = set(current.reasoning_model_ids)
        up_reas = set(upstream.reasoning_model_ids)
        cur_eff_ids = set(current.reasoning_efforts.keys())
        up_eff_ids = set(upstream.reasoning_efforts.keys())
        cur_mo_ids = set(current.max_output_tokens.keys())
        up_mo_ids = set(upstream.max_output_tokens.keys())

        self.added_image = _sorted(up_img - cur_img)
        self.removed_image = _sorted(cur_img - up_img)
        self.added_reasoning = _sorted(up_reas - cur_reas)
        self.removed_reasoning = _sorted(cur_reas - up_reas)
        self.added_effort = _sorted(up_eff_ids - cur_eff_ids)
        self.removed_effort = _sorted(cur_eff_ids - up_eff_ids)
        self.changed_effort = _sorted(
            mid
            for mid in up_eff_ids & cur_eff_ids
            if current.reasoning_efforts.get(mid) != upstream.reasoning_efforts.get(mid)
        )
        self.added_max_output = _sorted(up_mo_ids - cur_mo_ids)
        self.removed_max_output = _sorted(cur_mo_ids - up_mo_ids)
        self.changed_max_output = _sorted(
            mid
            for mid in up_mo_ids & cur_mo_ids
            if current.max_output_tokens.get(mid) != upstream.max_output_tokens.get(mid)
        )

    def has_diff(self) -> bool:
        return self.version_changed or any(
            (
                self.added_image,
                self.removed_image,
                self.added_reasoning,
                self.removed_reasoning,
                self.added_effort,
                self.removed_effort,
                self.changed_effort,
                self.added_max_output,
                self.removed_max_output,
                self.changed_max_output,
            )
        )


# ── render catalog.py ────────────────────────────────────────────────────────


def _py_str(value: str) -> str:
    return json.dumps(value)


def render_catalog(package_version: str, metadata: ModelMetadata) -> str:
    image_entries = "\n".join(
        f'    {_py_str(mid)}: ("text", "image"),' for mid in sorted(metadata.image_model_ids)
    )
    reasoning_entries = "\n".join(
        f'    {_py_str(mid)}: True,' for mid in sorted(metadata.reasoning_model_ids)
    )
    effort_entries = "\n".join(
        f'    {_py_str(mid)}: ({", ".join(_py_str(e) for e in efforts)}),'
        for mid, efforts in sorted(metadata.reasoning_efforts.items())
    )
    max_output_entries = "\n".join(
        f'    {_py_str(mid)}: {value:_},' for mid, value in sorted(metadata.max_output_tokens.items())
    )

    return f'''"""Command Code model catalog snapshot.

Generated from command-code@{package_version} by `python sync_catalog.py --write`.
Do not edit manually.
"""

from __future__ import annotations

# The CLI version this snapshot was generated from. Bump on re-sync.
COMMAND_CODE_CLI_VERSION = {_py_str(package_version)}

MODEL_EFFORTS: dict[str, tuple[str, ...]] = {{
{effort_entries}
}}

MODEL_INPUT_MODALITIES: dict[str, tuple[str, ...]] = {{
{image_entries}
}}

MODEL_REASONING: frozenset[str] = frozenset(
    {{
{reasoning_entries}
    }}
)

MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {{
{max_output_entries}
}}

DEFAULT_MAX_OUTPUT_TOKENS = 65_536


def input_modalities_for_model(model_id: str) -> tuple[str, ...]:
    return MODEL_INPUT_MODALITIES.get(model_id, ("text",))


def supports_image_input(model_id: str) -> bool:
    return "image" in input_modalities_for_model(model_id)


def is_reasoning_model(model_id: str) -> bool:
    return model_id in MODEL_REASONING


def efforts_for_model(model_id: str) -> tuple[str, ...]:
    return MODEL_EFFORTS.get(model_id, ())


def max_output_tokens_for_model(model_id: str) -> int:
    return MODEL_MAX_OUTPUT_TOKENS.get(model_id, DEFAULT_MAX_OUTPUT_TOKENS)
'''


def update_readme_catalog_version(readme: str, package_version: str) -> str:
    pattern = re.compile(r"command-code@\d+\.\d+\.\d+(?:[-+][^`\s,]+)?")
    if not pattern.search(readme):
        raise ValueError("Could not find the README catalog version")
    return pattern.sub(f"command-code@{package_version}", readme)


# ── report ───────────────────────────────────────────────────────────────────


def _format_list(model_ids: list[str]) -> str:
    return ", ".join(f"`{mid}`" for mid in model_ids) if model_ids else "None"


def metadata_report(package_version, current, upstream, diff: ModelMetadataDiff) -> str:
    status = "❌ Drift detected" if diff.has_diff() else "✅ Metadata is current"
    lines = [
        "## Command Code static model metadata",
        "",
        f"**{status}**",
        "",
        f"- Repository snapshot: `command-code@{current.cli_version}`",
        f"- Inspected package: `command-code@{package_version}`",
        f"- Image-capable models: {len(current.image_model_ids)} repository / {len(upstream.image_model_ids)} upstream",
        f"- Reasoning models: {len(current.reasoning_model_ids)} repository / {len(upstream.reasoning_model_ids)} upstream",
        f"- Models with selectable efforts: {len(current.reasoning_efforts)} repository / {len(upstream.reasoning_efforts)} upstream",
        f"- Model-specific output limits: {len(current.max_output_tokens)} repository / {len(upstream.max_output_tokens)} upstream",
    ]
    if upstream.unrecognized_efforts:
        lines.append(
            f"- ⚠️ Effort values not seen before: {_format_list(upstream.unrecognized_efforts)} "
            "— carried into the snapshot, but confirm the endpoint accepts them"
        )
    lines += [
        "",
        "| Change | Models |",
        "| --- | --- |",
        f"| CLI version | {'`' + current.cli_version + '` → `' + package_version + '`' if diff.version_changed else 'Current'} |",
        f"| New image support | {_format_list(diff.added_image)} |",
        f"| Removed image support | {_format_list(diff.removed_image)} |",
        f"| New reasoning models | {_format_list(diff.added_reasoning)} |",
        f"| Removed reasoning models | {_format_list(diff.removed_reasoning)} |",
        f"| New effort metadata | {_format_list(diff.added_effort)} |",
        f"| Removed effort metadata | {_format_list(diff.removed_effort)} |",
        f"| Changed reasoning efforts | {_format_list(diff.changed_effort)} |",
        f"| New output limits | {_format_list(diff.added_max_output)} |",
        f"| Removed output limits | {_format_list(diff.removed_max_output)} |",
        f"| Changed output limits | {_format_list(diff.changed_max_output)} |",
        "",
    ]
    return "\n".join(lines)


# ── fetch command-code tarball ───────────────────────────────────────────────


def _run_npm(args: list[str], cwd: str) -> str:
    import os

    npm = which("npm.cmd") if os.name == "nt" else which("npm")
    if not npm:
        raise RuntimeError("npm not found on PATH (needed to fetch command-code)")
    if os.name != "nt":
        result = subprocess.run([npm, *args], cwd=cwd, capture_output=True, text=True)
    else:
        # npm is a .cmd shim on Windows, so it needs cmd.exe; build the command
        # line with list2cmdline so every argument is quoted for the shell
        # (shutil.which may return a space-containing path).
        result = subprocess.run(
            subprocess.list2cmdline([npm, *args]),
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"npm {args} failed: {result.stderr.strip()}")
    return result.stdout


def _resolve_package_spec(package_spec: str, directory: str) -> str:
    if package_spec != "command-code@latest":
        return package_spec
    stdout = _run_npm(["view", package_spec, "version", "--json", "--prefer-online"], directory)
    return f"command-code@{json.loads(stdout)}"


def inspect_packed_package(package_spec: str):
    directory = tempfile.mkdtemp(prefix="commandcode-model-check-")
    try:
        resolved = _resolve_package_spec(package_spec, directory)
        stdout = _run_npm(["pack", resolved, "--json", "--prefer-online"], directory)
        packed = json.loads(stdout)
        if not isinstance(packed, list) or len(packed) != 1 or "filename" not in packed[0]:
            raise ValueError("Expected npm pack to return one package")
        filename = packed[0]["filename"]

        import os

        with tarfile.open(os.path.join(directory, filename)) as tar:
            try:
                # Python 3.12+ warns (and 3.14 defaults) without an explicit
                # extraction filter; npm tarballs are plain files/dirs.
                tar.extractall(directory, filter="data")
            except TypeError:  # pragma: no cover - Python without tar filters
                tar.extractall(directory)

        package_dir = Path(directory) / "package"
        package_json = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        package_version = package_json.get("version")
        if not isinstance(package_version, str):
            raise ValueError("Expected command-code package.json to contain a version")

        models_reference = (package_dir / MODELS_REFERENCE_PATH).read_text(encoding="utf-8")
        cli_bundle = (package_dir / CLI_BUNDLE_PATH).read_text(encoding="utf-8")
        metadata = command_code_model_metadata_from_contents(models_reference, cli_bundle)
        return package_version, metadata
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# ── exit codes (workflow contract) ───────────────────────────────────────────
# 0 = metadata current, 1 = drift detected (report/PR path), 2 = the check could
# not run at all (npm or parser failure). The workflow keys its PR steps on 1
# and fails the job on 2, so an error can never be reported as drift.
#
# The split matters for *data* surprises too: an upstream table that parses fine
# but carries values this project has not seen (a new reasoning-effort level) is
# drift, so it lands in a reviewable PR. Only an unreadable table — no rows, a
# duplicate id, a malformed row, a missing bundle marker — is exit 2.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    write = "--write" in sys.argv
    package_spec = _validate_package_spec(
        next((a for a in sys.argv if a.startswith("command-code@")), "command-code@latest")
    )

    current = import_current_metadata()
    current_version = current.cli_version
    upstream_version, upstream = inspect_packed_package(package_spec)
    diff = ModelMetadataDiff(current, upstream, current_version, upstream_version)
    report = metadata_report(upstream_version, current, upstream, diff)
    print(report)

    if write:
        rendered = render_catalog(upstream_version, upstream)
        CATALOG_PATH.write_text(rendered, encoding="utf-8")
        if README_PATH.exists():
            README_PATH.write_text(
                update_readme_catalog_version(README_PATH.read_text(encoding="utf-8"), upstream_version),
                encoding="utf-8",
            )
        print(f"Synchronized static metadata with command-code@{upstream_version}.")
        return EXIT_OK

    if diff.has_diff():
        print(
            f"CHANGE: static model metadata differs from command-code@{upstream_version}. "
            "Run `python sync_catalog.py --write` to update catalog.py.",
            file=sys.stderr,
        )
        return EXIT_DRIFT
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
