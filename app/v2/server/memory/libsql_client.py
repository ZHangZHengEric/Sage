"""Async remote libSQL transport using the Hrana HTTP pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class LibSQLError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Remote libSQL operation failed ({code})")


@dataclass(frozen=True)
class StatementResult:
    rows: list[list]
    affected: int


def _statement(sql, args=(), *, rows=False):
    return {
        "sql": sql,
        "args": [
            {"type": "integer", "value": str(value)} if isinstance(value, int)
            else {"type": "text", "value": value}
            for value in args
        ],
        "want_rows": rows,
    }


def _result(result) -> StatementResult:
    return StatementResult(
        rows=[
            [int(cell["value"]) if cell["type"] == "integer" else cell.get("value") for cell in row]
            for row in result["rows"]
        ],
        affected=result["affected_row_count"],
    )


class LibSQLClient:
    def __init__(self, url: str, auth_token: str | None = None) -> None:
        endpoint = urlsplit(url)
        if (endpoint.scheme not in {"libsql", "http", "https"} or not endpoint.hostname
                or endpoint.username is not None or endpoint.query or endpoint.fragment):
            raise ValueError("SAGE_SERVER_LIBSQL_URL must be a remote libsql://, https:// or http:// URL")
        self._url = endpoint._replace(
            scheme="https" if endpoint.scheme == "libsql" else endpoint.scheme,
            path=endpoint.path.rstrip("/") + "/v2/pipeline",
        ).geturl()
        self._headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> LibSQLClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _request(self, request):
        if self._http is None:
            self._http = httpx.AsyncClient(headers=self._headers, timeout=30.0)
        try:
            response = await self._http.post(
                self._url, json={"baton": None, "requests": [request, {"type": "close"}]},
            )
            response.raise_for_status()
            execution, close = response.json()["results"]
        except httpx.HTTPStatusError as exc:
            raise LibSQLError(f"HTTP {exc.response.status_code}") from None
        except httpx.RequestError as exc:
            raise LibSQLError(type(exc).__name__) from None
        except (KeyError, TypeError, ValueError):
            raise LibSQLError("INVALID_RESPONSE") from None
        for result in (execution, close):
            if result["type"] == "error":
                raise LibSQLError(result["error"].get("code", "SQL_ERROR"))
        return execution["response"]["result"]

    async def execute(self, sql, args=(), *, rows=False) -> StatementResult:
        result = await self._request({"type": "execute", "stmt": _statement(sql, args, rows=rows)})
        return _result(result)

    async def transaction(self, *statements: tuple[str, tuple, bool]) -> list[StatementResult]:
        steps = [{"stmt": _statement("BEGIN IMMEDIATE")}]
        for sql, args, rows in (*statements, ("COMMIT", (), False)):
            steps.append({
                "condition": {"type": "ok", "step": len(steps) - 1},
                "stmt": _statement(sql, args, rows=rows),
            })
        # Closing the stream rolls back any transaction whose COMMIT was skipped.
        result = await self._request({"type": "batch", "batch": {"steps": steps}})
        for error in result["step_errors"]:
            if error is not None:
                raise LibSQLError(error.get("code", "SQL_ERROR"))
        return [_result(item) for item in result["step_results"][1:-1]]
