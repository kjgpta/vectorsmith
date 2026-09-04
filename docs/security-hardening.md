# Production hardening

Hub: [documentation home](index.md). Security model: [enterprise.md](enterprise.md).

```bash
vectorsmith validate tools.yaml --enterprise --strict --env-file .env
vectorsmith validate tools.yaml --policy-builtin enterprise,pci,soc2
```

The HTTP security/runtime surface and backend stability are separate claims.
All current adapters emit experimental warning `VB2024`, so
`--enterprise --strict` remains non-zero until the selected backend completes
its live fault and supported-version matrix. Do not suppress that warning to
describe an adapter as stable. Evidence:
[backend conformance](conformance.md).

## `--enterprise` rules

| Code | Rule |
|---|---|
| VE001 | `authoring.define_tool: true` is an error |
| VE002 | `tenancy.mode: none` and no `must` filter on a tool |
| VE003 | `output.limit_max` > 100 |
| VE004 | Connection `url` / `dsn` / `host` is not `${VAR}` (checked on raw YAML) |
| VE005 | Meta tools still advertised (warning; use `--no-meta-tools`) |
| VE006 | Builtin auth on a public URL without HTTPS (serve-time) |
| VE007 | `defaults.embedding.provider: fastembed` (warning) |

`--profile enterprise` and a present `profiles.enterprise` block merge `security.hardening` at **validate, serve, and `connect`/`load_tools`** (0.2.0: this is a runtime refuse, not a CI-only lint). `disable_authoring` / `disable_meta_tools` win over `--enable-define` / `--meta-tools`; `require_tenancy`, `max_limit_max`, and `allowed_backends` refuse start. Multi-project HTTP unions every file's flags (strictest authoring/meta; tracing/metrics if any project enables them).

## Checklist

1. Secrets only via `${VAR}` under allowed interpolation paths
2. `--auth jwt` or `api_key` in front of HTTP; never `--auth none` on a public bind
3. `security.tenancy.mode: claim` (or header) plus YAML `must` filters
4. `security.rbac.enabled` with explicit roles; `deny_tools` for authoring
5. `observability.audit.enabled` to a file (0600) or HTTP sink
6. `serve --no-meta-tools` unless a Desktop host needs the freeze workaround
7. `output.limit_max` ≤ 100; `output.redact` for PAN / tokens
8. Two replicas + Redis auth store ([Kubernetes](deploy/kubernetes.md))
9. `--shutdown-grace-s 30` and `--log-format json`
10. CI: `validate --enterprise --strict`

## Identity profiles are not interchangeable

- **Desktop / stdio:** there is no authenticated request identity on the MCP pipe. Use
  literal `static_filters` for one fixed tenant and run a separate process/catalog for each
  security boundary.
- **HTTP:** authenticated JWT or API-key claims can populate `CallContext`; claim/header
  tenancy and RBAC are enforced per request. This is the profile for shared remote service
  processes.
- **Python in-process:** the application is the trust boundary. Pass
  `ctx=CallContext(...)` to `BoundTools.call()` (and to Anthropic `execute()`), or provide
  `vectorsmith_context` through supported framework context/config objects. Omitting it
  remains backward compatible but cannot satisfy claim-based tenancy.

Do not describe static stdio tenancy as authenticated identity, and do not assume an
in-process caller is trusted unless the application constructs the context from an
authenticated request.

Policy packs (`pci`, `soc2`) ship in `vectorsmith_core/policy/` and run in-process. Custom `--policy path.rego` runs `opa eval` with `{"tds": ...}` on stdin; each Rego `deny` becomes **POL001**. **POL000** if the `opa` CLI is missing or eval fails.

`parameters[].resolve.kind: directory` caches distinct values **per process**. Replicas do not share that cache.
