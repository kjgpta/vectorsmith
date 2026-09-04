"""Pluggable embedding providers (no live vendor APIs)."""

from __future__ import annotations

from typing import Any

import pytest

from vectorsmith_core.api import EnvCredentialResolver, load_project
from vectorsmith_core.compilepkg.validator import live_contract_issues
from vectorsmith_core.embed.cache import EmbedCache
from vectorsmith_core.embed.http import HttpEmbedProvider
from vectorsmith_core.embed.models import resolve_dims
from vectorsmith_core.embed.registry import reset_providers
from vectorsmith_core.errors import EmbeddingError
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.tds.models import EmbeddingConfig


def _src(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tds_version": "1",
        "connections": {"main": {"backend": "qdrant", "url": "http://localhost:6333"}},
        "tools": [
            {
                "name": "search_invoices",
                "description": "Search invoices by client status and due date for billing.",
                "target": {"connection": "main", "collection": "invoices"},
                "query": {"param": "query"},
            }
        ],
    }
    data.update(kw)
    return data


def test_string_defaults_still_compile() -> None:
    project = load_project(_src(), env={"QDRANT_URL": "http://localhost:6333"})
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert plan.embedding == "fastembed/BAAI/bge-small-en-v1.5"
    assert plan.embed_spec is not None
    assert plan.embed_spec.provider == "fastembed"


def test_object_defaults_and_query_override() -> None:
    src = _src()
    src["defaults"] = {
        "embedding": {
            "provider": "http",
            "model": "gateway-default",
            "dims": 1536,
            "config": {"base_url": "https://example.test/v1/embeddings"},
        }
    }
    src["tools"][0]["query"] = {
        "param": "query",
        "embedding": {
            "provider": "openai",
            "model": "text-embedding-3-large",
            "dims": 3072,
        },
    }
    project = load_project(src, env={"QDRANT_URL": "http://localhost:6333"})
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert plan.embedding == "text-embedding-3-large"
    assert plan.embed_spec is not None
    assert plan.embed_spec.provider == "openai"
    assert plan.embed_spec.dims == 3072


def test_explicit_dims_match_live_collection() -> None:
    src = _src()
    src["defaults"] = {
        "embedding": {"provider": "http", "model": "custom", "dims": 3072}
    }
    project = load_project(src, env={"QDRANT_URL": "http://localhost:6333"})
    plans = {n: t.plan for n, t in project.tools.items() if t.plan}
    issues = live_contract_issues(
        project.tds,
        plans,
        {"main:invoices": {"dim": 3072, "fields": ["tenant"]}},
    )
    assert not any(i.code == "VB2017" for i in issues)


def test_wrong_dims_vb2017() -> None:
    src = _src()
    src["defaults"] = {
        "embedding": {"provider": "http", "model": "custom", "dims": 3072}
    }
    project = load_project(src, env={"QDRANT_URL": "http://localhost:6333"})
    plans = {n: t.plan for n, t in project.tools.items() if t.plan}
    issues = live_contract_issues(
        project.tds,
        plans,
        {"main:invoices": {"dim": 384, "fields": ["tenant"]}},
    )
    assert any(i.code == "VB2017" for i in issues)


def test_unknown_model_without_dims_vb2018() -> None:
    src = _src()
    src["defaults"] = {"embedding": {"provider": "http", "model": "mystery-v9"}}
    project = load_project(src, env={"QDRANT_URL": "http://localhost:6333"})
    plans = {n: t.plan for n, t in project.tools.items() if t.plan}
    issues = live_contract_issues(
        project.tds,
        plans,
        {"main:invoices": {"dim": 384, "fields": ["tenant"]}},
    )
    assert any(i.code == "VB2018" for i in issues)


def test_resolve_dims_requires_explicit_for_unknown() -> None:
    with pytest.raises(EmbeddingError):
        resolve_dims("totally-unknown/model")
    assert resolve_dims("x", EmbeddingConfig(provider="http", model="x", dims=8)) == 8


def test_embed_config_interpolation_and_secret_lint() -> None:
    src = _src()
    src["defaults"] = {
        "embedding": {
            "provider": "http",
            "model": "gw",
            "dims": 8,
            "config": {"api_key": "${EMBED_API_KEY}", "base_url": "${EMBED_BASE_URL}"},
        }
    }
    project = load_project(
        src,
        env={
            "QDRANT_URL": "http://localhost:6333",
            "EMBED_API_KEY": "not-a-secret-short",
            "EMBED_BASE_URL": "https://example.test/emb",
        },
    )
    spec = project.tds.defaults.embedding
    assert spec.config["base_url"] == "https://example.test/emb"

    dirty = _src()
    dirty["defaults"] = {
        "embedding": {
            "provider": "http",
            "model": "gw",
            "dims": 8,
            "config": {"api_key": "sk-thislookslikearealsecretkeyvalue"},
        }
    }
    project = load_project(dirty, env={"QDRANT_URL": "http://localhost:6333"})
    assert any(i.code == "VB1003" for i in project.issues)


@pytest.mark.asyncio
async def test_http_provider_batches_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_providers()
    calls: list[list[str]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            }

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _Resp:
            calls.append(list(json["input"]))
            return _Resp()

    import sys
    from types import ModuleType

    fake = ModuleType("httpx")

    class AsyncClient:
        def __init__(self, timeout: float = 0) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _Client:
            return _Client()

        async def __aexit__(self, *args: object) -> None:
            return None

    fake.AsyncClient = AsyncClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)

    provider = HttpEmbedProvider()
    cfg = EmbeddingConfig(
        provider="http",
        model="m",
        dims=2,
        config={"base_url": "https://example.test/v1", "batch_size": 2},
    )
    vecs = await provider.embed(["a", "b", "c", "d"], "m", config=cfg)
    assert len(vecs) == 4
    assert len(calls) == 2
    assert calls[0] == ["a", "b"]
    assert calls[1] == ["c", "d"]

    class _Boom:
        async def __aenter__(self) -> _Boom:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("gateway down")

    class AsyncClientFail:
        def __init__(self, timeout: float = 0) -> None:
            del timeout

        async def __aenter__(self) -> _Boom:
            return _Boom()

        async def __aexit__(self, *args: object) -> None:
            return None

    fake.AsyncClient = AsyncClientFail  # type: ignore[attr-defined]
    provider2 = HttpEmbedProvider()
    with pytest.raises(EmbeddingError, match="gateway down"):
        await provider2.embed(["z"], "m", config=cfg)


def test_embed_cache_lru() -> None:
    cache = EmbedCache(maxsize=2)
    cache.put("http", "m", "a", [1.0])
    cache.put("http", "m", "b", [2.0])
    cache.put("http", "m", "c", [3.0])
    assert cache.get("http", "m", "a") is None
    assert cache.get("http", "m", "c") == [3.0]


@pytest.mark.asyncio
async def test_readyz_live_embed(tmp_path: Any) -> None:
    from pathlib import Path

    from starlette.testclient import TestClient

    from vectorsmith_cli.http.app import build_app
    from vectorsmith_cli.http.builtin_oauth.store import AuthStore

    class FakeEmbed:
        async def health(self) -> bool:
            return False

        async def embed(
            self, texts: list[str], model: str, *, config: Any = None
        ) -> list[list[float]]:
            return [[0.0] * 3 for _ in texts]

    project = load_project(_src(), env={"QDRANT_URL": "http://localhost:6333"})
    engine = Engine(
        project,
        credential_resolver=EnvCredentialResolver({}),
        embed_provider=FakeEmbed(),
    )
    app = build_app(
        engine=engine,
        enable_define=False,
        auth="none",
        public_url="http://127.0.0.1",
        store=AuthStore(Path(tmp_path) / "auth.db"),
        drafts_path=Path(tmp_path) / "tools.drafts.yaml",
        live_embed=True,
    )
    client = TestClient(app)
    res = client.get("/readyz")
    assert res.status_code == 503
    assert res.json()["embed"]["ok"] is False
    assert client.get("/healthz").status_code == 200
