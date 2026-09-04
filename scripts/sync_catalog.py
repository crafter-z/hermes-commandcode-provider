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

TEXT_ONLY_MARKER = ',__name(isKnownTextOnlyModel,"isKnownTextOnlyModel")'
VALID_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max"}

# ── Data model (matches TS CommandCodeModelMetadata) ─────────────────────────


class ModelMetadata:
    def __init__(
        self,
        image_model_ids: list[str],
        reasoning_model_ids: list[str],
        reasoning_efforts: dict[str, list[str]],
        max_output_tokens: dict[str, int],
        cli_version: str = "",
    ):
        self.image_model_ids = image_model_ids
        self.reasoning_model_ids = reasoning_model_ids
        self.reasoning_efforts = reasoning_efforts
        self.max_output_tokens = max_output_tokens
        self.cli_version = cli_version


def _sorted(values) -> list[str]:
    return sorted(set(values))


# ── Parser: models.md ────────────────────────────────────────────────────────
_MODELS_ROW_RE = re.compile(r"^\| `([^`]+)` \| [^|]* \| [^|]* \| ([^|]*) \|")


def parse_models_reference(markdown: str):
    model_ids = set()
    reasoning_efforts: dict[str, list[str]] = {}

    for line in markdown.split("\n"):
        match = _MODELS_ROW_RE.match(line)
        if not match:
            continue
        model_id = match.group(1)
        efforts_column = match.group(2).strip()
        if not model_id or not efforts_column:
            raise ValueError(f"Could not parse model row: {line}")
        if model_id in model_ids:
            raise ValueError(f"Duplicate model id in reference: {model_id}")
        model_ids.add(model_id)

        if efforts_column == "—":  # em-dash → no selectable efforts
            continue
        efforts = [e.strip() for e in efforts_column.split(",")]
        if not efforts or any(e not in VALID_EFFORTS for e in efforts):
            raise ValueError(f"Unexpected reasoning efforts for {model_id}: {efforts_column}")
        reasoning_efforts[model_id] = efforts

    if not model_ids:
        raise ValueError("No model rows found in Command Code reference")

    return {
        "model_ids": _sorted(model_ids),
        "reasoning_efforts": dict(sorted(reasoning_efforts.items())),
    }


# ── Parser: cli.mjs ──────────────────────────────────────────────────────────


def parse_known_text_only_model_ids(bundle: str) -> list[str]:
    marker_index = bundle.find(TEXT_ONLY_MARKER)
    if marker_index < 0:
        raise ValueError("Could not find Command Code's isKnownTextOnlyModel catalog")

    set_start = bundle.rfind("new Set([", 0, marker_index)
    if set_start < 0:
        raise ValueError("Could not find the text-only model set")

    array_start = set_start + len("new Set(")
    array_end = marker_index - 1
    literal = bundle[array_start:array_end]
    parsed = json.loads(literal)
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        raise ValueError("Expected the text-only model catalog to be strings")
    return _sorted(parsed)


def _model_object(bundle: str, model_id: str) -> str:
    """Return the brace-delimited model object literal for *model_id*."""
    anchor = f'{{id:"{model_id}",inputModalities:'
    start = bundle.find(anchor)
    if start < 0:
        raise ValueError(f"Could not find model metadata for {model_id}")

    depth = 0
    quote = ""
    escaped = False
    end = start
    while end < len(bundle):
        char = bundle[end]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        else:
            if char in ('"', "'", "`"):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return bundle[start : end + 1]
        end += 1

    raise ValueError(f"Unterminated model metadata for {model_id}")


def parse_bundle_model_capabilities(bundle: str, model_ids: list[str]):
    reasoning_model_ids = []
    max_output_tokens: dict[str, int] = {}

    for model_id in model_ids:
        entry = _model_object(bundle, model_id)
        if "reasoning:!0" in entry or "reasoningEfforts:[" in entry:
            reasoning_model_ids.append(model_id)
        max_output = re.search(r"maxOutputTokens:([^,}]+)", entry)
        if max_output:
            value = float(max_output.group(1))
            if not (value > 0 and value == int(value)):
                raise ValueError(f"Unexpected max output tokens for {model_id}: {max_output.group(1)}")
            max_output_tokens[model_id] = int(value)

    return {
        "reasoning_model_ids": _sorted(reasoning_model_ids),
        "max_output_tokens": dict(sorted(max_output_tokens.items())),
    }


def command_code_model_metadata_from_contents(
    models_reference: str, cli_bundle: str
) -> ModelMetadata:
    reference = parse_models_reference(models_reference)
    text_only_model_ids = set(parse_known_text_only_model_ids(cli_bundle))
    capabilities = parse_bundle_model_capabilities(cli_bundle, reference["model_ids"])

    image_model_ids = [mid for mid in reference["model_ids"] if mid not in text_only_model_ids]
    return ModelMetadata(
        image_model_ids=_sorted(image_model_ids),
        reasoning_model_ids=capabilities["reasoning_model_ids"],
        reasoning_efforts=reference["reasoning_efforts"],
        max_output_tokens=capabilities["max_output_tokens"],
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
        # npm is a .cmd shim on Windows; route through the shell. shutil.which
        # may return a space-containing path; quote it so the shell treats it
        # as one token.
        result = subprocess.run(
            f'"{npm}" {" ".join(args)}',
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


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    write = "--write" in sys.argv
    package_spec = next(
        (a for a in sys.argv if a.startswith("command-code@")), "command-code@latest"
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
        return 0

    if diff.has_diff():
        print(
            f"CHANGE: static model metadata differs from command-code@{upstream_version}. "
            "Run `python sync_catalog.py --write` to update catalog.py.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        sys.exit(1)
