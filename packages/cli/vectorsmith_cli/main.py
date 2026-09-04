"""Typer entrypoint: serve, validate, introspect, test, init, drafts, approve, auth."""

from __future__ import annotations

from pathlib import Path

import typer

from vectorsmith_cli.authoring_cmd import run_discover, run_drift, run_eval
from vectorsmith_cli.drafts_cmd import run_approve, run_drafts
from vectorsmith_cli.identity import DEFAULT_SERVER_NAME
from vectorsmith_cli.init_cmd import run_init
from vectorsmith_cli.introspect_cmd import run_introspect
from vectorsmith_cli.migrate_cmd import run_migrate
from vectorsmith_cli.serve_http import serve_http
from vectorsmith_cli.serve_stdio import serve_stdio
from vectorsmith_cli.test_cmd import run_test
from vectorsmith_cli.validate_cmd import run_validate

app = typer.Typer(name="vectorsmith", no_args_is_help=True)


@app.command()
def init(
    directory: Path = typer.Argument(Path("."), help="Where to write tools.yaml"),
    print_desktop_config: bool = typer.Option(False, "--print-desktop-config"),
    name: str = typer.Option(
        DEFAULT_SERVER_NAME,
        "--name",
        help="mcpServers key to print (you choose this in Claude / your SDK)",
    ),
) -> None:
    """Write an example tools.yaml and .env.example."""
    run_init(directory, print_desktop_config=print_desktop_config, name=name)


@app.command()
def validate(
    tools: Path = typer.Argument(..., help="Path to tools.yaml"),
    live: bool = typer.Option(False, "--live"),
    live_embed: bool = typer.Option(
        False, "--live-embed", help="Smoke-test the embedding provider (implies --live)"
    ),
    as_json: bool = typer.Option(False, "--json"),
    strict: bool = typer.Option(False, "--strict"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    enterprise: bool = typer.Option(False, "--enterprise"),
    profile: str | None = typer.Option(None, "--profile"),
    policy: Path | None = typer.Option(None, "--policy"),
    policy_builtin: str | None = typer.Option(None, "--policy-builtin"),
) -> None:
    """Validate a TDS file."""
    raise SystemExit(
        run_validate(
            tools,
            live=live or live_embed,
            live_embed=live_embed,
            as_json=as_json,
            strict=strict,
            env_file=env_file,
            enterprise=enterprise,
            profile=profile,
            policy=policy,
            policy_builtin=policy_builtin,
        )
    )


@app.command("serve")
def serve_cmd(
    tools: list[Path] = typer.Argument(..., help="Path(s) to tools.yaml"),
    http: str | None = typer.Option(None, "--http", help="HOST:PORT for streamable HTTP"),
    auth: str = typer.Option(
        "builtin",
        "--auth",
        help="HTTP auth: builtin | jwt | api_key | none (none is loopback only)",
    ),
    public_url: str | None = typer.Option(None, "--public-url"),
    jwt_issuer: str | None = typer.Option(None, "--jwt-issuer"),
    jwt_audience: str | None = typer.Option(None, "--jwt-audience"),
    jwks_url: str | None = typer.Option(None, "--jwks-url"),
    api_keys_file: Path | None = typer.Option(None, "--api-keys-file"),
    auth_store: str = typer.Option("sqlite", "--auth-store", help="sqlite | redis"),
    redis_url: str | None = typer.Option(None, "--redis-url"),
    audit_log: Path | None = typer.Option(None, "--audit-log"),
    audit_sink: str | None = typer.Option(None, "--audit-sink"),
    audit_url: str | None = typer.Option(None, "--audit-url"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    enable_define: bool = typer.Option(False, "--enable-define"),
    meta_tools: bool = typer.Option(
        True,
        "--meta-tools/--no-meta-tools",
        help=(
            "Advertise list_available_tools / run_tool (Desktop freeze workaround). "
            "Off = compiled tools only."
        ),
    ),
    watch: bool = typer.Option(True, "--watch/--no-watch"),
    live_embed: bool = typer.Option(
        False, "--live-embed", help="Check embed provider health on GET /readyz"
    ),
    name: str = typer.Option(
        DEFAULT_SERVER_NAME,
        "--name",
        help="MCP serverInfo.name; also the mcpServers key you set in Claude / your SDK",
    ),
    route_by_claim: str | None = typer.Option(None, "--route-by-claim"),
    default_project: str | None = typer.Option(None, "--default-project"),
    shutdown_grace_s: int = typer.Option(30, "--shutdown-grace-s"),
    log_format: str = typer.Option("text", "--log-format", help="text | json"),
    log_level: str = typer.Option("info", "--log-level"),
) -> None:
    """Serve tools over MCP stdio or HTTP."""
    if http:
        serve_http(
            tools if len(tools) > 1 else tools[0],
            bind=http,
            auth=auth,
            public_url=public_url,
            env_file=env_file,
            enable_define=enable_define,
            include_meta=meta_tools,
            live_embed=live_embed,
            name=name,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            jwks_url=jwks_url,
            api_keys_file=api_keys_file,
            auth_store=auth_store,
            redis_url=redis_url,
            audit_log=audit_log,
            audit_sink=audit_sink,
            audit_url=audit_url,
            route_by_claim=route_by_claim,
            default_project=default_project,
            shutdown_grace_s=shutdown_grace_s,
            log_format=log_format,
            log_level=log_level,
        )
        return
    serve_stdio(
        tools[0],
        env_file=env_file,
        enable_define=enable_define,
        include_meta=meta_tools,
        watch=watch,
        name=name,
        audit_log=audit_log,
        audit_sink=audit_sink,
        audit_url=audit_url,
        log_format=log_format,
        log_level=log_level,
    )


@app.command("test")
def test_cmd(
    tools: Path = typer.Argument(...),
    tool: str = typer.Argument(...),
    args: str = typer.Option("{}", "--args"),
    show_plan: bool = typer.Option(False, "--show-plan"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Smoke-test one compiled tool. Agents must call tools over MCP via serve."""
    raise SystemExit(run_test(tools, tool, args, show_plan=show_plan, env_file=env_file))


@app.command()
def introspect(
    tools: Path = typer.Argument(...),
    connection: str = typer.Option(..., "--connection"),
    out: Path = typer.Option(Path("schema.json"), "--out"),
    collections: str | None = typer.Option(None, "--collections"),
    redact_examples: bool = typer.Option(False, "--redact-examples"),
    audit: bool = typer.Option(False, "--audit"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Export a metadata-only schema.json."""
    raise SystemExit(
        run_introspect(
            tools,
            connection=connection,
            out=out,
            collections=collections,
            redact_examples=redact_examples,
            audit=audit,
            env_file=env_file,
        )
    )


@app.command()
def discover(
    tools: Path = typer.Argument(...),
    connection: str = typer.Option(..., "--connection"),
    collections: str | None = typer.Option(None, "--collections"),
    out: Path = typer.Option(Path("tools.discovered.drafts.yaml"), "--out"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    experimental: bool = typer.Option(False, "--experimental"),
) -> None:
    """Generate pending schema-backed drafts without changing tools.yaml."""
    raise SystemExit(
        run_discover(
            tools,
            connection=connection,
            collections=collections,
            out=out,
            env_file=env_file,
            experimental=experimental,
        )
    )


@app.command("eval")
def eval_cmd(
    tools: Path = typer.Argument(...),
    scenarios: Path = typer.Argument(...),
    out: Path = typer.Option(Path("vectorsmith-eval.json"), "--out"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    experimental: bool = typer.Option(False, "--experimental"),
) -> None:
    """Run checked-in contract scenarios against the normal execution engine."""
    raise SystemExit(
        run_eval(
            tools,
            scenarios,
            out=out,
            env_file=env_file,
            experimental=experimental,
        )
    )


@app.command()
def drift(
    tools: Path = typer.Argument(...),
    schema: Path = typer.Argument(...),
    connection: str = typer.Option(..., "--connection"),
    out: Path = typer.Option(Path("vectorsmith-drift.json"), "--out"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    experimental: bool = typer.Option(False, "--experimental"),
) -> None:
    """Compare a metadata-only schema export with live introspection."""
    raise SystemExit(
        run_drift(
            tools,
            schema,
            connection=connection,
            out=out,
            env_file=env_file,
            experimental=experimental,
        )
    )


@app.command()
def drafts(
    action: str = typer.Argument(..., help="list | reject"),
    name: str | None = typer.Argument(None),
) -> None:
    """List or reject pending drafts."""
    run_drafts(action, name)


@app.command()
def approve(
    name: str = typer.Argument(...),
    file: Path = typer.Option(Path("tools.yaml"), "--file"),
    approver: str | None = typer.Option(None, "--approver"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Promote a draft into tools.yaml."""
    run_approve(name, file, approver=approver, dry_run=dry_run)


@app.command()
def auth(
    action: str = typer.Argument(..., help="rotate-secret | revoke"),
) -> None:
    """Builtin OAuth admin: rotate-secret | revoke."""
    from vectorsmith_cli.http.builtin_oauth.store import AuthStore

    store = AuthStore()
    if action == "rotate-secret":
        secret = store.rotate_secret()
        dest = store.write_secret_once(secret)
        print(f"New access secret written to {dest} (mode 0600)", file=__import__("sys").stderr)
        return
    if action == "revoke":
        store.revoke_all()
        print("All tokens revoked", file=__import__("sys").stderr)
        return
    print("usage: auth rotate-secret | revoke", file=__import__("sys").stderr)
    raise SystemExit(2)


@app.command()
def migrate(
    tools: Path = typer.Argument(..., help="Path to tools.yaml"),
    from_version: str = typer.Option("1", "--from"),
    to_version: str = typer.Option("2", "--to"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Rewrite a TDS file between versions."""
    raise SystemExit(
        run_migrate(
            tools,
            from_version=from_version,
            to_version=to_version,
            dry_run=dry_run,
            write=write,
        )
    )
