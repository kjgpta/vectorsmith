# Repository map

This is what GitHub visitors see and where the rest lives.

| Path | What it is |
|---|---|
| [README.md](https://github.com/kjgpta/vectorsmith/blob/main/README.md) | Landing page: why VectorSmith exists, YAML sketch, two consumption paths |
| [docs/](index.md) | Full manual (this tree). Start at [library surface](library.md) for extras / routes / exceptions |
| [docs/conformance.md](conformance.md) | Live backend versions, contract coverage, skips, and stability gates |
| [examples/](https://github.com/kjgpta/vectorsmith/tree/main/examples) | Invoice + ticket YAML, enterprise JWT/tenancy/RBAC, agent apps, MCP host configs |
| [packages/core](https://github.com/kjgpta/vectorsmith/tree/main/packages/core) | Compiler source (`vectorsmith_core`) — bundled into the published wheel, not a PyPI project |
| [packages/cli](https://github.com/kjgpta/vectorsmith/tree/main/packages/cli) | Published `vectorsmith` — CLI + `load_tools` / `connect` |
| [tests/conformance](https://github.com/kjgpta/vectorsmith/tree/main/tests/conformance) | Deterministic six-backend live contract, seed fixtures, and independent oracle |
| [deploy-templates/](https://github.com/kjgpta/vectorsmith/blob/main/deploy-templates/README.md) | Docker / Kubernetes / Cloud Run / Fly for HTTP MCP |
| [CONTRIBUTING.md](https://github.com/kjgpta/vectorsmith/blob/main/CONTRIBUTING.md) | Dev setup, PR rules, versioning |
| [SUPPORT.md](https://github.com/kjgpta/vectorsmith/blob/main/SUPPORT.md) | Where to ask for help |
| [SECURITY.md](https://github.com/kjgpta/vectorsmith/blob/main/SECURITY.md) | Vulnerability reports (private) |
| [CHANGELOG.md](changelog.md) | User-visible changes |
| [LICENSE](https://github.com/kjgpta/vectorsmith/blob/main/LICENSE) · [NOTICE](https://github.com/kjgpta/vectorsmith/blob/main/NOTICE) | Apache-2.0 |

Do not import `Engine`. Application code uses `from vectorsmith import load_tools` or `connect`, or the `vectorsmith` CLI.

Current support evidence and the rules for promoting an adapter are documented
under [backend conformance](conformance.md). Local evidence and product-research
notes under `.internal/` are deliberately not published.
