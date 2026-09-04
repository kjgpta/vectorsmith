"""TDS pydantic models. Fields ARE the spec (cursor §2 + Phase-1 backend addendum)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, model_validator

DType = Literal["keyword", "integer", "float", "boolean", "datetime", "keyword[]"]
LcdOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"]
ExtOp = Literal["exists", "is_null", "contains_any", "contains_all", "like", "text_match"]
Op = Union[LcdOp, ExtOp]
ToolName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
FieldPath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"),
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")  # loader walks model_extra → VB0001 warnings


class BuiltinToolsSpec(_Base):
    semantic_search: bool = False
    get_by_id: bool = False
    count: bool = False
    list_collections: bool = False


class StaticFilter(_Base):
    path: FieldPath
    op: LcdOp = "eq"
    value: object


class StaticFilters(_Base):
    """``must`` + ``must_not``. A bare YAML list is coerced to ``must``."""

    must: list[StaticFilter] = Field(default_factory=list)
    must_not: list[StaticFilter] = Field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.must or self.must_not)

    def __iter__(self) -> Iterator[StaticFilter]:  # type: ignore[override]
        return iter(self.must)


def _coerce_static_filters(value: object) -> StaticFilters:
    if value is None:
        return StaticFilters()
    if isinstance(value, StaticFilters):
        return value
    if isinstance(value, list):
        return StaticFilters(must=[StaticFilter.model_validate(x) for x in value])
    if isinstance(value, dict):
        return StaticFilters.model_validate(value)
    return value  # type: ignore[return-value]


StaticFilterBlock = Annotated[StaticFilters, BeforeValidator(_coerce_static_filters)]


class RedactPattern(_Base):
    regex: str
    replacement: str = "[redacted]"


class OutputRedactRule(_Base):
    path: FieldPath
    mode: Literal["omit", "hash", "mask", "pattern"] = "omit"
    patterns: list[RedactPattern] | None = None


class OutputSpec(_Base):
    fields: list[FieldPath] | None = None
    limit_default: int = Field(default=10, ge=1, le=500)
    limit_max: int = Field(default=50, ge=1, le=500)
    include_score: bool = True
    include_id: bool = True
    max_field_length: int | None = Field(default=None, ge=1, le=100_000)
    truncate_suffix: str = "…"
    redact: list[OutputRedactRule] = Field(default_factory=list)


class BuiltinDefaults(_Base):
    collections: list[str] | None = None
    static_filters: StaticFilterBlock = Field(default_factory=StaticFilters)
    output: OutputSpec | None = None
    descriptions: dict[str, str] | None = None


class VaultCredSpec(_Base):
    addr: str | None = None
    path: str | None = None
    role: str | None = None


class AwsSmSpec(_Base):
    secret_id: str | None = None
    region: str | None = None


class K8sSpec(_Base):
    secret: str | None = None
    key: str | None = None
    namespace: str | None = None


class ConnectionCredentials(_Base):
    provider: Literal["env", "vault", "aws_sm", "k8s"] = "env"
    vault: VaultCredSpec = Field(default_factory=VaultCredSpec)
    aws_sm: AwsSmSpec = Field(default_factory=AwsSmSpec)
    k8s: K8sSpec = Field(default_factory=K8sSpec)


class _ConnBase(_Base):
    builtin_tools: BuiltinToolsSpec = BuiltinToolsSpec()
    builtin_defaults: BuiltinDefaults = BuiltinDefaults()
    credentials: ConnectionCredentials = Field(default_factory=ConnectionCredentials)


class QdrantConn(_ConnBase):
    backend: Literal["qdrant"]
    url: str
    api_key: str | None = None


class PgvectorConn(_ConnBase):
    backend: Literal["pgvector"]
    dsn: str
    table: str | None = None
    vector_column: str | None = "embedding"  # None or explicit `mode: table` ⇒ TABLE MODE
    mode: Literal["vector", "table"] | None = None
    id_column: str = "id"


class ChromaConn(_ConnBase):
    backend: Literal["chroma"]
    url: str
    auth_token: str | None = None


class PineconeConn(_ConnBase):
    backend: Literal["pinecone"]
    api_key: str
    host: str
    namespace: str | None = None


class WeaviateConn(_ConnBase):
    backend: Literal["weaviate"]
    url: str
    api_key: str | None = None
    tenant: str | None = None
    embedding_mode: Literal["auto", "client", "server"] = "auto"


class MilvusConn(_ConnBase):
    backend: Literal["milvus"]
    uri: str
    token: str | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None


ConnectionSpec = Annotated[
    QdrantConn | PgvectorConn | ChromaConn | PineconeConn | WeaviateConn | MilvusConn,
    Field(discriminator="backend"),
]


class Target(_Base):
    connection: str
    collection: str | object  # object = ParamRef — SYNTHETIC ONLY (VB2015 guards users)


class EmbeddingConfig(_Base):
    """Resolved embedder. String YAML form is coerced via ``from_legacy``."""

    provider: Literal["fastembed", "openai", "azure_openai", "http", "cohere"] = "fastembed"
    model: str = "BAAI/bge-small-en-v1.5"
    dims: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_legacy(cls, value: str) -> EmbeddingConfig:
        provider: Literal["fastembed", "openai", "azure_openai", "http", "cohere"] = (
            "fastembed"
        )
        model = value
        prefixes = (
            ("azure_openai/", "azure_openai"),
            ("openai/", "openai"),
            ("cohere/", "cohere"),
            ("http/", "http"),
        )
        for prefix, name in prefixes:
            if value.startswith(prefix):
                provider = name  # type: ignore[assignment]
                model = value[len(prefix) :]
                break
        return cls(provider=provider, model=model)

    @property
    def identity(self) -> str:
        return self.model


def _coerce_embed(value: object) -> EmbeddingConfig | None:
    if value is None or value == "":
        return None
    if isinstance(value, EmbeddingConfig):
        return value
    if isinstance(value, str):
        return EmbeddingConfig.from_legacy(value)
    if isinstance(value, dict):
        return EmbeddingConfig.model_validate(value)
    return value  # type: ignore[return-value]


def _coerce_embed_required(value: object) -> EmbeddingConfig:
    parsed = _coerce_embed(value)
    if parsed is None:
        return EmbeddingConfig.from_legacy("fastembed/BAAI/bge-small-en-v1.5")
    return parsed


EmbedSpec = Annotated[EmbeddingConfig | None, BeforeValidator(_coerce_embed)]
EmbedRequired = Annotated[EmbeddingConfig, BeforeValidator(_coerce_embed_required)]


class ExpandSpec(_Base):
    enabled: bool = False
    provider: Literal["openai", "http", "none"] = "none"
    model: str = "gpt-4o-mini"
    variants: int = Field(default=3, ge=1, le=5)
    config: dict[str, Any] = Field(default_factory=dict)


class QuerySpec(_Base):
    param: str = "query"
    required: bool = False
    embedding: EmbedSpec = None
    mode: Literal["dense", "hybrid"] = "dense"
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    min_score: float | None = None
    ef: int | None = Field(default=None, ge=1, le=10_000)
    expand: ExpandSpec = Field(default_factory=ExpandSpec)


class ResolveSpec(_Base):
    kind: Literal["directory", "enum"] = "enum"
    connection: str | None = None
    collection: str | None = None
    field: str | None = None
    min_confidence: float = Field(default=0.72, ge=0.0, le=1.0)
    max_candidates: int = Field(default=5000, ge=1, le=50_000)
    cache_ttl_s: int = Field(default=600, ge=1, le=86_400)


class ParamSpec(_Base):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    path: FieldPath | None = None
    dtype: DType | Literal["unknown"] = "keyword"
    op: Op | None = None
    required: bool = False
    description: str | None = None
    enum: list[str | int | float] | None = Field(default=None, max_length=100)
    default: object | None = None
    max: float | None = None
    resolve: ResolveSpec | None = None


class FetchSpec(_Base):
    k_param: str = "limit"
    overfetch_factor: int = Field(default=10, ge=1, le=50)
    max_candidates: int = Field(default=2000, ge=10, le=20000)


class RetrieveBody(_Base):
    target: Target
    query: QuerySpec | None = None
    filter: dict[str, Any] | None = None
    fetch: FetchSpec = FetchSpec()


class RetrieveStep(_Base):
    retrieve: RetrieveBody


class PostFilterBody(_Base):
    expr: str


class PostFilterStep(_Base):
    post_filter: PostFilterBody


class PerGroup(_Base):
    sort_by: FieldPath
    desc: bool = True
    take: int | str = 3


class GroupByBody(_Base):
    keys: list[FieldPath] = Field(min_length=1, max_length=3)
    per_group: PerGroup | None = None


class GroupByStep(_Base):
    group_by: GroupByBody


class SortBody(_Base):
    by: FieldPath
    desc: bool = True


class SortStep(_Base):
    sort: SortBody


class ProjectBody(_Base):
    fields: list[FieldPath] = Field(min_length=1)


class ProjectStep(_Base):
    project: ProjectBody


PipelineStep = Union[RetrieveStep, PostFilterStep, GroupByStep, SortStep, ProjectStep]


class RerankSpec(_Base):
    enabled: bool = False
    provider: Literal["cohere", "cross_encoder", "http"] = "http"
    model: str = "rerank-english-v3.0"
    retrieve_k: int = Field(default=50, ge=1, le=500)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(_Base):
    name: ToolName
    description: Annotated[str, Field(min_length=20, max_length=1024)]
    kind: Literal["search", "lookup", "count", "scroll", "pipeline", "meta"] = "search"
    target: Target | None = None
    query: QuerySpec | None = None
    parameters: list[ParamSpec] = Field(default_factory=list, max_length=12)
    static_filters: StaticFilterBlock = Field(default_factory=StaticFilters)
    filter_logic: Literal["and"] = "and"
    steps: list[PipelineStep] | None = None
    output: OutputSpec = OutputSpec()
    rerank: RerankSpec = Field(default_factory=RerankSpec)
    _synthetic: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _shape(self) -> ToolSpec:
        if self.kind == "pipeline":
            assert self.steps and isinstance(self.steps[0], RetrieveStep), (
                "pipeline: retrieve first"
            )
            assert self.target is None
        elif self.kind == "meta":
            assert not self.query and not self.parameters and not self.static_filters
        else:
            assert self.target is not None
            assert not self.steps
        return self


class Defaults(_Base):
    embedding: EmbedRequired = Field(
        default_factory=lambda: EmbeddingConfig.from_legacy(
            "fastembed/BAAI/bge-small-en-v1.5"
        )
    )


class AuthoringSpec(_Base):
    define_tool: bool = False


class TenancyConfig(_Base):
    """Request-scoped payload isolation. Never compiled into the MCP schema."""

    mode: Literal["none", "static", "claim", "header"] = "none"
    claim: str | None = None
    header: str = "X-Tenant-Id"
    path: FieldPath = "tenant_id"
    op: Literal["eq"] = "eq"
    enforce: Literal["strict", "override", "warn"] = "strict"


class JWTAuthConfig(_Base):
    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    principal_claim: str = "sub"
    claims_prefix: str = ""


class APIKeyAuthConfig(_Base):
    header: str = "Authorization"
    scheme: Literal["Bearer", "ApiKey", "none"] = "Bearer"
    keys_file: str | None = None


class AuthConfig(_Base):
    mode: Literal["builtin", "jwt", "api_key", "none"] | None = None
    jwt: JWTAuthConfig = Field(default_factory=JWTAuthConfig)
    api_key: APIKeyAuthConfig = Field(default_factory=APIKeyAuthConfig)


class RoleSpec(_Base):
    allow: list[str] = Field(default_factory=list)


class RBACConfig(_Base):
    enabled: bool = False
    default_role: str = "viewer"
    role_claim: str = "roles"
    roles: dict[str, RoleSpec] = Field(default_factory=dict)
    deny_tools: list[str] = Field(default_factory=list)


class RateWindowSpec(_Base):
    requests_per_minute: int | None = None
    embed_requests_per_minute: int | None = None
    llm_requests_per_minute: int | None = None


class RateLimitConfig(_Base):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    enabled: bool = False
    store: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    global_limits: RateWindowSpec = Field(
        default_factory=RateWindowSpec, validation_alias="global"
    )
    per_principal: RateWindowSpec = Field(default_factory=RateWindowSpec)
    per_tool: dict[str, str] = Field(default_factory=dict)


class SecurityConfig(_Base):
    tenancy: TenancyConfig = Field(default_factory=TenancyConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rbac: RBACConfig = Field(default_factory=RBACConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)


class AuditInclude(_Base):
    args: bool = True
    result_count: bool = True
    latency_ms: bool = True
    search_mode: bool = True
    warnings: bool = True


class AuditRedact(_Base):
    arg_fields: list[str] = Field(default_factory=lambda: ["password", "token", "secret"])
    row_fields: list[str] = Field(default_factory=list)


class AuditConfig(_Base):
    enabled: bool = False
    sink: Literal["stdout", "file", "http", "otlp"] = "stdout"
    format: Literal["jsonl", "json"] = "jsonl"
    path: str | None = None
    url: str | None = None
    include: AuditInclude = Field(default_factory=AuditInclude)
    exclude_tools: list[str] = Field(default_factory=list)
    redact: AuditRedact = Field(default_factory=AuditRedact)


class TracingConfig(_Base):
    enabled: bool = False
    exporter: Literal["otlp", "console"] = "otlp"
    endpoint: str = "http://localhost:4318"
    service_name: str = "vectorsmith"


class MetricsConfig(_Base):
    enabled: bool = False
    port: int = Field(default=9090, ge=1, le=65535)


class ObservabilityConfig(_Base):
    audit: AuditConfig = Field(default_factory=AuditConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


class HardeningSpec(_Base):
    disable_authoring: bool = True
    disable_meta_tools: bool = True
    require_tenancy: bool = True
    max_limit_max: int = 100
    allowed_backends: list[str] | None = None


class ProfileSecurity(_Base):
    hardening: HardeningSpec = Field(default_factory=HardeningSpec)


class NamedProfile(_Base):
    security: ProfileSecurity = Field(default_factory=ProfileSecurity)


class Profiles(_Base):
    enterprise: NamedProfile | None = None


class CatalogMeta(_Base):
    tool_catalog_version: str | None = None
    deprecated: list[dict[str, Any]] = Field(default_factory=list)


class TDSFile(_Base):
    tds_version: Literal["1", "2"] = "1"
    meta: CatalogMeta = Field(default_factory=CatalogMeta)
    connections: dict[str, ConnectionSpec]
    defaults: Defaults = Defaults()
    authoring: AuthoringSpec = AuthoringSpec()
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    profiles: Profiles = Field(default_factory=Profiles)
    tools: list[ToolSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs(self) -> TDSFile:
        names = [t.name for t in self.tools]
        assert len(names) == len(set(names)), "duplicate tool names"
        for t in self.tools:
            targets = (
                [t.target]
                if t.target
                else [
                    s.retrieve.target
                    for s in (t.steps or [])
                    if isinstance(s, RetrieveStep)
                ]
            )
            for tg in targets:
                assert tg is not None
                assert tg.connection in self.connections, (
                    f"{t.name}: unknown connection '{tg.connection}'"
                )
        return self


def is_table_mode(conn: PgvectorConn) -> bool:
    """Table mode when ``mode=='table'`` or ``vector_column is None``."""
    return conn.mode == "table" or conn.vector_column is None


TDSFile.model_rebuild()
ToolSpec.model_rebuild()
