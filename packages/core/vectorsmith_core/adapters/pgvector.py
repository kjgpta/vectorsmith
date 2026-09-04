"""pgvector adapter (vector + table mode). SQL via psycopg.sql only."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import PGVECTOR_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or
from vectorsmith_core.tds.models import PgvectorConn, is_table_mode


class PgvectorAdapter(VectorBackendAdapter):
    caps: ClassVar = PGVECTOR_CAPS

    def __init__(self, spec: PgvectorConn, creds: dict[str, str]) -> None:
        self.spec = spec
        self.dsn = creds.get("dsn") or spec.dsn
        self.vector_capable = not is_table_mode(spec)
        self._pool: Any = None

    def _ident(self) -> Any:
        from psycopg import sql
        table = self.spec.table or "invoices"
        return sql.Identifier(*table.split(".")) if "." in table else sql.Identifier(table)

    def compile_filter(self, node: IRNode | None) -> object:
        from psycopg import sql
        params: list[Any] = []
        clause = _sql_clause(node, params, id_column=self.spec.id_column)
        return {"sql": clause, "params": params, "composed": sql.SQL("{}").format(clause)}

    async def _conn(self) -> Any:
        if self._pool is not None:
            return self._pool
        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:
            raise BackendUnreachable(
                detail="pgvector extra not installed: pip install vectorsmith-core[pgvector]"
            ) from exc
        self._pool = AsyncConnectionPool(conninfo=self.dsn, min_size=1, max_size=8, open=False)
        await self._pool.open()
        return self._pool

    async def health(self) -> bool:
        try:
            pool = await self._conn()
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        return [self.spec.table] if self.spec.table else []

    async def search(self, req: SearchRequest) -> RowBatch:
        if not self.vector_capable:
            if req.vector is None:
                return await self._scroll(req)
            raise InvalidArgumentsError(
                detail="table mode does not support search — use lookup/count/scroll/pipeline"
            )
        if req.vector is None:
            return await self._scroll(req)
        from psycopg import sql
        compiled = self.compile_filter(
            req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        )
        filter_params = list(compiled["params"]) if isinstance(compiled, dict) else []
        vec_col = sql.Identifier(self.spec.vector_column or "embedding")
        id_col = sql.Identifier(self.spec.id_column)
        where = compiled["sql"] if isinstance(compiled, dict) else sql.SQL("TRUE")
        params = [req.vector, *filter_params, req.vector, req.limit, req.offset or 0]
        query = sql.SQL(
            "SELECT {id} AS _id, *, ({vec} <=> %s::vector) AS _distance "
            "FROM {table} WHERE {where} "
            "ORDER BY {vec} <=> %s::vector, {id} LIMIT %s OFFSET %s"
        ).format(id=id_col, vec=vec_col, table=self._ident(), where=where)
        try:
            pool = await self._conn()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(query, params)
                cols = [d.name for d in cur.description] if cur.description else []
                rows = [
                    _normalize_row(
                        dict(zip(cols, row, strict=False)),
                        id_column=self.spec.id_column,
                        projection=req.projection,
                        with_score=req.with_score,
                    )
                    for row in await cur.fetchall()
                ]
            return RowBatch(rows=rows, exhausted=len(rows) < req.limit)
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def _scroll(self, req: SearchRequest) -> RowBatch:
        from psycopg import sql
        compiled = self.compile_filter(
            req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        )
        params = list(compiled["params"]) if isinstance(compiled, dict) else []
        where = compiled["sql"] if isinstance(compiled, dict) else sql.SQL("TRUE")
        id_col = sql.Identifier(self.spec.id_column)
        params.extend([req.limit, req.offset or 0])
        query = sql.SQL(
            "SELECT {id} AS _id, * FROM {table} WHERE {where} "
            "ORDER BY {id} LIMIT %s OFFSET %s"
        ).format(id=id_col, table=self._ident(), where=where)
        try:
            pool = await self._conn()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(query, params)
                cols = [d.name for d in cur.description] if cur.description else []
                rows = [
                    _normalize_row(
                        dict(zip(cols, row, strict=False)),
                        id_column=self.spec.id_column,
                        projection=req.projection,
                        with_score=False,
                    )
                    for row in await cur.fetchall()
                ]
            return RowBatch(rows=rows, exhausted=len(rows) < req.limit)
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        from psycopg import sql
        _ = collection
        compiled = self.compile_filter(filter_ir)
        params = list(compiled["params"]) if isinstance(compiled, dict) else []
        where = compiled["sql"] if isinstance(compiled, dict) else sql.SQL("TRUE")
        query = sql.SQL("SELECT count(*) FROM {table} WHERE {where}").format(
            table=self._ident(), where=where
        )
        try:
            pool = await self._conn()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        batch = await self._scroll(
            SearchRequest(collection=collection or (self.spec.table or ""), limit=n)
        )
        return batch.rows

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        table_name = collection or self.spec.table
        if not table_name:
            return None
        if "." in table_name:
            schema_name, bare_table = table_name.rsplit(".", 1)
        else:
            schema_name, bare_table = "public", table_name
        columns_sql = """
            SELECT column_name, data_type, is_nullable, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        indexes_sql = """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
        """
        vector_type_sql = """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s AND a.attname = %s
        """
        try:
            pool = await self._conn()
            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(columns_sql, (schema_name, bare_table))
                columns = await cur.fetchall()
                await cur.execute(indexes_sql, (schema_name, bare_table))
                indexes = await cur.fetchall()
                vector_type = None
                if self.spec.vector_column:
                    await cur.execute(
                        vector_type_sql,
                        (schema_name, bare_table, self.spec.vector_column),
                    )
                    vector_row = await cur.fetchone()
                    vector_type = str(vector_row[0]) if vector_row else None
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        index_text = "\n".join(str(row[1]) for row in indexes)
        fields = []
        dim_match = re.search(r"vector\((\d+)\)", vector_type or "")
        dim = int(dim_match.group(1)) if dim_match else None
        for name, data_type, nullable, udt_name in columns:
            if name == self.spec.vector_column:
                continue
            dtype = _pg_dtype(str(data_type), str(udt_name))
            fields.append(
                {
                    "path": str(name),
                    "dtype": dtype,
                    "nullable": nullable == "YES",
                    "indexed": str(name) in index_text,
                    "provenance": "native",
                }
            )
        return {
            "dim": dim,
            "sparse": False,
            "fields": fields,
            "indexed_paths": {
                str(field["path"]): "sql"
                for field in fields
                if field["indexed"]
            },
            "provenance": "native",
        }

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


def _pg_dtype(data_type: str, udt_name: str) -> str:
    text = f"{data_type} {udt_name}".lower()
    if "array" in text or udt_name.startswith("_"):
        return "keyword[]"
    if any(token in text for token in ("smallint", "integer", "bigint", "int")):
        return "integer"
    if any(token in text for token in ("numeric", "decimal", "real", "double", "float")):
        return "float"
    if "bool" in text:
        return "boolean"
    if any(token in text for token in ("date", "time")):
        return "datetime"
    return "keyword"


def _sql_clause(node: IRNode | None, params: list[Any], *, id_column: str) -> Any:
    from psycopg import sql
    if node is None:
        return sql.SQL("TRUE")
    if isinstance(node, And):
        parts = [_sql_clause(c, params, id_column=id_column) for c in node.children]
        return sql.SQL(" AND ").join(sql.SQL("(") + p + sql.SQL(")") for p in parts)
    if isinstance(node, Or):
        parts = [_sql_clause(c, params, id_column=id_column) for c in node.children]
        return sql.SQL(" OR ").join(sql.SQL("(") + p + sql.SQL(")") for p in parts)
    assert isinstance(node, Cond)
    if node.path == "id":
        col: Any = sql.Identifier(id_column)
        json_col: Any | None = None
    else:
        path = node.path.split(".")
        params.append(path)
        col = sql.SQL("payload #>> %s")
        json_col = sql.SQL("payload #> %s")
    if node.op == "exists":
        if json_col is None:
            return sql.SQL("TRUE")
        present = sql.SQL("COALESCE(jsonb_typeof(") + json_col + sql.SQL(") <> 'null', FALSE)")
        return present if node.value is not False else sql.SQL("NOT ") + present
    if node.op == "is_null":
        if json_col is None:
            return col + (
                sql.SQL(" IS NULL") if node.value is not False else sql.SQL(" IS NOT NULL")
            )
        null_test = json_col + sql.SQL(" = 'null'::jsonb")
        return null_test if node.value is not False else sql.SQL("NOT (") + null_test + sql.SQL(")")
    compare_col = col
    if isinstance(node.value, bool):
        compare_col = sql.SQL("NULLIF({}, '')::boolean").format(col)
    elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        compare_col = sql.SQL("NULLIF({}, '')::numeric").format(col)
    if node.op == "eq":
        params.append(node.value)
        return compare_col + sql.SQL(" = %s")
    if node.op == "ne":
        params.append(node.value)
        return compare_col + sql.SQL(" <> %s")
    if node.op in {"gt", "gte", "lt", "lte"}:
        ops = {
            "gt": sql.SQL(" > %s"),
            "gte": sql.SQL(" >= %s"),
            "lt": sql.SQL(" < %s"),
            "lte": sql.SQL(" <= %s"),
        }
        params.append(node.value)
        return compare_col + ops[node.op]
    if node.op == "in":
        params.append(_as_list(node.value))
        return compare_col + sql.SQL(" = ANY(%s)")
    if node.op == "nin":
        params.append(_as_list(node.value))
        return compare_col + sql.SQL(" <> ALL(%s)")
    if node.op in {"contains_any", "contains_all"}:
        if json_col is None:
            raise InvalidArgumentsError(
                detail=f"pgvector does not support '{node.op}' on the id column"
            )
        values = [str(value) for value in _as_list(node.value)]
        if not values:
            raise InvalidArgumentsError(detail=f"pgvector '{node.op}' requires values")
        params.append(values)
        operator = sql.SQL(" ?| %s") if node.op == "contains_any" else sql.SQL(" ?& %s")
        return json_col + operator
    if node.op == "like":
        params.append(node.value)
        return col + sql.SQL(" ILIKE %s")
    raise InvalidArgumentsError(detail=f"pgvector does not support op '{node.op}'")


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _normalize_row(
    row: dict[str, Any],
    *,
    id_column: str,
    projection: list[str] | None,
    with_score: bool,
) -> dict[str, Any]:
    payload = row.pop("payload", None)
    normalized = dict(payload) if isinstance(payload, dict) else {}
    normalized.update(row)
    normalized["_id"] = row.get(id_column, row.get("_id"))
    normalized.pop("embedding", None)
    distance = normalized.pop("_distance", None)
    if with_score and isinstance(distance, (int, float)):
        normalized["_score"] = 1.0 / (1.0 + max(0.0, float(distance)))
    if projection is not None:
        keep = {*projection, "_id"}
        if with_score:
            keep.add("_score")
        normalized = {key: value for key, value in normalized.items() if key in keep}
    return normalized
