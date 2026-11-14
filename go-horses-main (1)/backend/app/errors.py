"""Erros no formato que o frontend entende: {"error": {"code", "message", "min_bid"?}}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("gohorses.errors")


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        min_bid: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.min_bid = min_bid
        self.extra = extra or {}


def _payload(code: str, message: str, *, min_bid: int | None = None, **extra: Any) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if min_bid is not None:
        error["min_bid"] = min_bid
    error.update(extra)
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, min_bid=exc.min_bid, **exc.extra),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = first.get("msg", "Dados inválidos.")
        if loc:
            message = f"{loc}: {message}"
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Erro na requisição."
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload("http_error", message),
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Erro inesperado", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_payload(
                "internal_error",
                "Erro interno no servidor. Tente novamente.",
            ),
        )
