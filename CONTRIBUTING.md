# Contributing

User-facing documentation lives in [`docs/`](docs/index.md) and is published at [kjgpta.github.io/vectorsmith](https://kjgpta.github.io/vectorsmith/). If you change YAML fields, CLI flags, or an integration path, update the matching page there (and the FAQ if the failure mode is new). Preview with `mkdocs serve` after `pip install 'mkdocs>=1.6,<2' mkdocs-material mkdocs-autorefs`.

## Setup

Python 3.11+. [uv](https://docs.astral.sh/uv/) is required.

```bash
uv sync
uv run ruff check .
uv run pytest -m "not conformance"
uv run lint-imports
```

`uv run mypy` covers `vectorsmith_core`. Adapter conformance tests need all
store SDKs plus the pinned local services:

```bash
uv sync --group dev --group conformance --frozen
docker compose up -d
PYTHONPATH=packages/core:packages/cli:. \
  uv run pytest tests/conformance --backend all --tb=short
docker compose down --volumes
```

Use one backend name (for example `--backend chroma`) for a focused run.
Conformance is not required for a typical PR while every backend remains
experimental; CI exposes it as a non-blocking diagnostic matrix. An advertised
capability must pass—do not weaken the oracle or threshold to make a backend
green. If the store cannot satisfy the contract, update its capability claim.
Details: [backend conformance](docs/conformance.md).

## Layout

| Path | Role |
|---|---|
| `packages/core` | `vectorsmith_core` (unpublished; bundled into the `vectorsmith` wheel) |
| `packages/cli` | Published **`vectorsmith`** — CLI + `load_tools` / `connect` |
| `docs/` | User documentation |
| `examples/` | Runnable samples |
| `tests/unit` | Fast tests (CI) |
| `tests/conformance` | Deterministic live contract and backend-independent oracle |

`vectorsmith_core` must not import `vectorsmith` or `vectorsmith_cli` (enforced by import-linter).

## Pull requests

- Keep changes focused. Do not mix refactors with feature work.
- Add or update a unit test when you change compiler, loader, or public API behavior.
- Update `docs/` if you change `tools.yaml` fields, CLI flags, or an integration path.
- Do not commit `.env`, credentials, or `tools.drafts.yaml`.
- Do not commit files under `.internal/` (unpublished notes).

## Versioning

Package versions live in:

- `packages/core/pyproject.toml`
- `packages/cli/pyproject.toml`
- `packages/core/vectorsmith_core/version.py` (`ENGINE_VERSION`, shown by `serve`)

Keep those three in sync. After a user-visible change, add a note to `CHANGELOG.md`.

## Publishing (maintainers)

Source: [github.com/kjgpta/vectorsmith](https://github.com/kjgpta/vectorsmith). **One** PyPI project: [`vectorsmith`](https://pypi.org/project/vectorsmith/). The compiler (`vectorsmith_core`) is bundled into that wheel; do not publish `vectorsmith-core`. Do not use an API token; the [Release](.github/workflows/release.yml) workflow uses [trusted publishing](https://docs.pypi.org/trusted-publishers/).

### One-time setup

1. Create a [PyPI](https://pypi.org/account/register/) account with 2FA (required).
2. Confirm the GitHub Actions environment `pypi` exists on this repo (the workflow already names it).
3. On PyPI, open **Account settings → Publishing** and add **one** pending publisher:

   | Field | Value |
   |---|---|
   | PyPI project name | `vectorsmith` |
   | Owner | `kjgpta` |
   | Repository | `vectorsmith` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   A pending publisher does **not** reserve the name until the first successful upload. Publish soon after adding it. If you already added a pending publisher for `vectorsmith-core`, delete it.

### Each release

1. Versions match in `packages/core/pyproject.toml`, `packages/cli/pyproject.toml`, and `ENGINE_VERSION`. Changelog is updated.
2. `uv lock` if you changed dependencies. Push to `main`.
3. Dry-run: **Actions → release → Run workflow** with `dry_run` checked (build + tests, no upload).
4. Tag and push: `git tag v0.2.0 && git push origin v0.2.0` (or **Run workflow** with `dry_run` unchecked). A `v*` tag always publishes.
5. Confirm [pypi.org/project/vectorsmith](https://pypi.org/project/vectorsmith/). Then `pip install "vectorsmith[qdrant]"` in a fresh venv.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
