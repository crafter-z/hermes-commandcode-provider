# hermes-commandcode-provider

A Hermes integration for [Command Code](https://commandcode.ai) — a **user-installed
provider profile override** plus a standalone **quota query** plugin. Ported from the
reference [pi-commandcode-provider](https://github.com/patlux/pi-commandcode-provider)
plugin, targeting the Command Code **Provider API** (GOAT plan path) — OpenAI chat
completions + Anthropic Messages, the `/alpha/*` usage endpoints, an always-live
model catalog, per-model metadata, pricing display, and a daily metadata drift check.

> Unofficial community integration. Not affiliated with or endorsed by Command Code.
> Requires a Command Code account, API key, and a plan with Provider API access.

## What it does

- **Live model catalog** — model IDs are **always fetched live** from
  `https://api.commandcode.ai/provider/v1/models`. They are **never hardcoded**; the
  snapshot only carries per-model *metadata* (image input, reasoning capability,
  selectable reasoning efforts, per-model output caps) that the API does not expose.
- **Two provider profiles** — `commandcode` (OpenAI chat completions) and
  `commandcode-anthropic` (Anthropic Messages), both registered as a
  `$HERMES_HOME` override that supersedes Hermes's bundled `commandcode` profile.
- **Per-model metadata hooks** — reasoning effort clamping, vision capability,
  per-model max-token caps, wired through `ProviderProfile` hooks so `/model`
  shows correct reasoning/vision/cost metadata.
- **Pricing injection** — Command Code's Provider API catalog has no prices, so a
  static table is injected into `agent.usage_pricing._OFFICIAL_DOCS_PRICING`
  (no editing of bundled core files; survives `hermes update`). Keys are
  `(provider, model)` for the plugin's own `commandcode` and
  `commandcode-anthropic` profiles. Injection is guaranteed before any session
  turn computes cost: the quota plugin's `on_session_start` hook re-runs a
  deferred install, and the provider profile's `fetch_models` does the same for
  profile-based sessions.
- **`/commandcode-quota`** — a standalone plugin slash command showing account
  usage/quota from the same alpha endpoints the Command Code CLI `/usage` uses
  (whoami, billing/credits, billing/subscriptions, usage/summary).
- **Metadata drift check** — `scripts/sync_catalog.py` regenerates the snapshot
  from the `command-code` npm CLI package, with a daily GitHub Actions job.

## Layout

```
plugins/model-providers/commandcode/      # $HERMES_HOME plugin override
  __init__.py        # both ProviderProfile profiles + metadata hooks + pricing inject
  cache.py           # on-disk model catalog cache + offline fallback (enrich/cache_path/…)
  catalog.py         # per-model metadata snapshot (generated; NOT model ids)
  pricing.py         # static pricing table + install_pricing()
  plugin.yaml        # manifest (kind: model-provider)
plugins/commandcode-quota/                # standalone plugin
  __init__.py        # register(ctx) → /commandcode-quota, -refresh, -status
  status.py          # /commandcode-refresh + /commandcode-status handlers
  quota.py           # alpha endpoint fetch + schema parsing
  quota_format.py    # text renderer
  plugin.yaml        # manifest (kind: standalone)
scripts/sync_catalog.py                   # metadata sync / drift-check (--write)
.github/workflows/commandcode-metadata.yml # daily drift PR + manual sync
tests/test_quota_plugin.py                # quota fetch/format contract test (run w/ python)
```

## Install

### 1. Provider profile override

Copy the override into Hermes's user plugin directory so it supersedes the bundled
`commandcode` profile (same name, last-writer-wins):

```sh
# Windows (HERMES_HOME = %LOCALAPPDATA%\hermes by default)
mkdir -p "$HERMES_HOME/plugins/model-providers"
cp -r plugins/model-providers/commandcode "$HERMES_HOME/plugins/model-providers/commandcode"
```

Set the API key:

```sh
export COMMANDCODE_API_KEY="user_..."
# or COMMAND_CODE_API_KEY (legacy alias)
```

**Model IDs are never hardcoded.** `/model` and `provider_model_ids('commandcode')`
fetch the live catalog from `/provider/v1/models` and merge the profile's
`fallback_models`. Set the API key to get the full live catalog; without it the
curated fallback list appears.

### 2. Quota plugin

```sh
mkdir -p "$HERMES_HOME/plugins"
cp -r plugins/commandcode-quota "$HERMES_HOME/plugins/commandcode-quota"
hermes plugins enable commandcode-quota
```

Then in a session: `/commandcode-quota`.

> Standalone plugins are opt-in — disable and re-enable via `hermes plugins`.
> The bundled `model-provider` plugins are loaded by `providers/` discovery and
> need no enable step; the quota **standalone** plugin does.

### 3. Catalog cache & refresh/status commands

Every live model fetch (`provider_model_ids`, `/model`) now persists the
enriched catalog to `<HERMES_HOME>/cache/commandcode-models.json` (written
atomically by `plugins/model-providers/commandcode/cache.py`), so the model
list and its live-observed `context_length` windows survive offline sessions —
`get_model_metadata` and the commands below fall back to that file when
`/models` is unreachable. The quota plugin registers two commands to manage and
inspect the cache:

- `/commandcode-refresh` — re-fetch the catalog (live first, disk-cache
  fallback). Live result: `Command Code model catalog refreshed (N models from
  live).` Unreachable but cached: `Command Code model catalog unchanged (N
  models remain available). <warning>`. Overlapping refreshes are coalesced
  (returns "refresh already in progress").
- `/commandcode-status` — redacted provider diagnostics: last refresh source
  (`live`/`cache`/`empty`), model count, last success/attempt ISO timestamps
  ("never" when unset), cache path, endpoint, and any warning. URLs are trimmed
  to `protocol://host/path` and key/token/secret values are scrubbed.

Cache location defaults to `<HERMES_HOME>/cache/commandcode-models.json`
(`HERMES_HOME` unset: `~/AppData/Local/hermes`); override it with
`COMMANDCODE_MODELS_CACHE`. The refresh fetch timeout (default 10 s) is
configurable via `COMMANDCODE_MODELS_TIMEOUT_MS`.

## Model metadata sync & drift

The `catalog.py` snapshot is generated from the `command-code` npm CLI package.
The Provider API `/models` endpoint returns only `id`/`name`/`context_length`;
reasoning capability, selectable efforts, image input, and per-model output caps
live in the CLI package's `reference/models.md` and `dist/cli.mjs`.

```sh
# Report-only: exit 1 if the checked-in snapshot drifted from upstream
python scripts/sync_catalog.py

# Regenerate catalog.py + README version
python scripts/sync_catalog.py --write

# Pin a specific CLI version
python scripts/sync_catalog.py command-code@1.47.0 --write
```

The GitHub Actions workflow runs the check daily; on drift it opens a draft PR
with the regenerated `catalog.py` for review. A manual `sync` dispatch regenerates
and pushes directly.

## Environment variables

- `COMMANDCODE_API_KEY` (or legacy `COMMAND_CODE_API_KEY`) — Provider API key.
- `COMMANDCODE_BASE_URL` / `COMMANDCODE_ANTHROPIC_BASE_URL` — per-profile base-URL
  overrides (proxy/custom deployment).
- `COMMANDCODE_MODELS_URL` — models-endpoint override (tests/mocks).
- `COMMANDCODE_MODELS_CACHE` — catalog cache file path override (default
  `<HERMES_HOME>/cache/commandcode-models.json`).
- `COMMANDCODE_MODELS_TIMEOUT_MS` — `/commandcode-refresh` live-fetch timeout in
  milliseconds (default `10000`).

## Notes & divergence

- **Pricing tiers**: Hermes `PricingEntry` supports a single tier threshold with
  whole-request `*_above` replacement. Single-threshold models (`grok-4.6`,
  `qwen3.7-plus`) map exactly; multi-threshold models (`qwen3.8-max`,
  `qwen3.7-flash`) collapse to their dominant flat rate (documented in
  `pricing.py`). DeepSeek V4 shows the documented off-peak rate (17h/day). The
  Command Code Usage page is authoritative for billed amounts.
- **No Go-plan `/alpha/generate` transport and no OAuth browser login** — this
  integration targets the Provider/GOAT path only. Add those only if you need
  Go-tier accounts.

## License

MIT
