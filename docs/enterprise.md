# Enterprise security model

Hub: [documentation home](index.md). Hardening checklist: [security-hardening.md](security-hardening.md).

VectorSmith is a **compiler**, not an identity provider or access plane. You own auth, host choice, and the store. This page is the security model the compiler and `serve` / `connect` enforce when you turn the knobs on.

**0.2.0** applies every layer below at process start. `validate --enterprise` is the CI gate; a non-compliant YAML now also refuses `serve` and `connect`.

## Layers

| Layer | Where | What it does |
|---|---|---|
| Hidden filters | `static_filters` | Always AND. The model never sees them |
| Request tenancy | `security.tenancy` | Extra payload filter from JWT claim or header |
| Auth | `--auth jwt` / `api_key` / `builtin` | Who is calling HTTP `/mcp` |
| RBAC | `security.rbac` | Which compiled tools that principal may invoke |
| Audit | `observability.audit` | One event per named tool call |
| Rate limits | `security.rate_limit` | Off by default; HTTP **429** |
| Output policy | `output.redact` | Applied before the result (and audit) leaves the process |

`--auth none` is loopback only (exit 3 off localhost). Builtin OAuth still requires `https://` `--public-url`.

## Tenancy

`security.tenancy.mode`:

- `none` — no request filter (YAML `static_filters` still apply)
- `static` — this process is one tenant; use `static_filters`
- `claim` — value from JWT (`claim: tenant_id`)
- `header` — value from an HTTP header

The engine ANDs `tenant_filter` with `must` / `must_not`. `enforce: strict` rejects a model argument that conflicts (**VB4010**).

Pick **one** isolation layer unless you intend both:

| Pattern | YAML | When |
|---|---|---|
| Claim (multi-tenant HTTP) | `tenancy.mode: claim` only | One process, many tenants from JWT |
| Static (one-tenant process) | `tenancy.mode: static` + `static_filters.must` tenant | Replica / namespace already isolated |
| Both (AND) | claim **and** a compile-time tenant filter | Rare: process is pinned to `acme` *and* JWT must match |

Copy-paste: [`examples/enterprise/tools.yaml`](https://github.com/kjgpta/vectorsmith/tree/main/examples/enterprise/tools.yaml) (claim) and [`tools.static.yaml`](https://github.com/kjgpta/vectorsmith/tree/main/examples/enterprise/tools.static.yaml) (static).

### Trust profiles

- Stdio has no authenticated caller identity. Use static filters and one
  process/catalog per security boundary.
- HTTP derives request context from JWT, API-key, or builtin OAuth state and is
  the profile for shared claim/header tenancy.
- Python in-process calls may pass `CallContext`, but the embedding application
  is responsible for authenticating the caller before constructing it.

These profiles are not interchangeable. Details and framework mappings:
[security hardening](security-hardening.md#identity-profiles-are-not-interchangeable)
and [Python API](python-api.md).

## Auth and RBAC

HTTP `--auth jwt` validates RS256 via JWKS (`vectorsmith[auth-jwt]`). `--auth api_key` reads a keys file. `--auth-store redis` shares builtin OAuth tokens across replicas. `GET /readyz` fetches JWKS so a down IdP takes the replica out of rotation.

`security.rbac.deny_tools` wins over `allow: ["*"]`. Checks apply to the **inner** name of `run_tool`.

## Audit

JSONL: `request_id`, `principal`, tool, connection, redacted args, result count, latency. Sinks: `file` (mode 0600), `http` (raw JSONL POST), `otlp` (OTLP HTTP JSON logs). Sink failures do not block the call. Default redact: `password`, `token`, `secret`. Multi-project `serve` uses each YAML’s audit block unless you pass `--audit-*`.

## Credentials

`connections.*.credentials.provider` defaults to `env`. `serve` / `connect` dispatch on the provider:

| Provider | Runtime | Required |
|---|---|---|
| `env` | `--env-file` / `env=` | `${VAR}` on connection fields |
| `vault` | HTTP KV read (`VAULT_ADDR`, `VAULT_TOKEN`, `credentials.vault.path`) | Secret JSON keys = connection fields (`url`, `api_key`, …) |
| `aws_sm` | Secrets Manager (`vectorsmith[creds-aws]`) | `credentials.aws_sm.secret_id` (**VB4041**) |
| `k8s` | In-cluster service account | `credentials.k8s.secret` (**VB4042**) |

Inject a `fetch` callable on `build_credential_resolver` for tests. Details: [tools.yaml → credentials](tools-yaml-reference.md#credentials).

## Rate limits

`security.rate_limit` is off by default. Per-principal / per-tool / embed windows. In-memory or `store: redis` (`vectorsmith[auth-redis]`; async client). HTTP **429** with `retry_after_s`.

## Production checklist

1. Run `validate --enterprise --strict` in CI. It intentionally remains
   non-zero for experimental backend warning `VB2024`; stable deployment claims
   require the [backend conformance](conformance.md) gate to pass.
2. `serve --http` with `--auth jwt` or `api_key` (never `--auth none` on a public bind)
3. `GET /readyz` as the readiness probe; `GET /healthz` for liveness
4. `--log-format json` and `observability.audit.enabled`
5. Helm / two replicas + Redis if you use builtin OAuth — [Kubernetes](deploy/kubernetes.md)

Directory parameter resolve caches in-process only (see [tools.yaml → resolve](tools-yaml-reference.md#parametersresolve)).

See [`examples/enterprise/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/enterprise). Full inventory: [library surface](library.md).
