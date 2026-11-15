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


# Nomes de campo e mensagens de validação em português: o frontend mostra o
# texto do erro direto para o usuário.
_FIELD_LABELS = {
    "display_name": "Nome de exibição",
    "email": "E-mail",
    "password": "Senha",
    "monthly_income_cents": "Renda mensal",
    "name": "Nome do item",
    "description": "Descrição",
    "category": "Categoria",
    "photos": "Fotos",
    "starting_price": "Preço inicial",
    "starts_at": "Início",
    "duration_seconds": "Duração",
    "amount": "Valor do lance",
    "filename": "Nome do arquivo",
    "content_type": "Tipo do arquivo",
    "size": "Tamanho do arquivo",
    "page": "Página",
    "q": "Busca",
    "status": "Estado",
    "token": "Link de upload",
    "Idempotency-Key": "Cabeçalho Idempotency-Key",
}

_HTTP_MESSAGES = {
    400: "Requisição inválida.",
    401: "Entre para continuar.",
    403: "Você não tem permissão para isso.",
    404: "Recurso não encontrado.",
    405: "Método não permitido.",
    413: "Conteúdo grande demais.",
    415: "Tipo de conteúdo não suportado.",
    429: "Muitas requisições. Tente de novo em instantes.",
}


def _validation_message(error: dict[str, Any]) -> str:
    kind = str(error.get("type", ""))
    ctx = error.get("ctx") or {}
    parts = [part for part in error.get("loc", []) if part not in {"body", "query", "path", "header"}]
    field = next((str(part) for part in parts if isinstance(part, str)), "")
    label = _FIELD_LABELS.get(field, field)

    if kind in {"json_invalid", "model_attributes_type", "dict_type"}:
        return "O corpo da requisição não é um JSON válido."
    if kind == "missing":
        detail = "é obrigatório"
    elif kind in {"string_too_short", "too_short"}:
        detail = f"precisa ter pelo menos {ctx.get('min_length', 1)} " + (
            "itens" if kind == "too_short" else "caracteres"
        )
    elif kind in {"string_too_long", "too_long"}:
        detail = f"pode ter no máximo {ctx.get('max_length', '?')} " + (
            "itens" if kind == "too_long" else "caracteres"
        )
    elif kind in {"greater_than", "greater_than_equal"}:
        bound = ctx.get("gt", ctx.get("ge"))
        detail = f"precisa ser maior {'que' if kind == 'greater_than' else 'ou igual a'} {bound}"
    elif kind in {"less_than", "less_than_equal"}:
        bound = ctx.get("lt", ctx.get("le"))
        detail = f"precisa ser menor {'que' if kind == 'less_than' else 'ou igual a'} {bound}"
    elif kind.startswith("int") or kind == "finite_number":
        detail = "precisa ser um número inteiro"
    elif kind.startswith("string"):
        detail = "precisa ser um texto"
    elif kind.startswith(("datetime", "date")):
        detail = "precisa ser uma data e hora válidas"
    elif kind.startswith("list"):
        detail = "precisa ser uma lista"
    elif field == "email":
        detail = "inválido"
    else:
        detail = "inválido"
    return f"{label}: {detail}." if label else "Dados inválidos."


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, min_bid=exc.min_bid, **exc.extra),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        message = _validation_message(errors[0]) if errors else "Dados inválidos."
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = _HTTP_MESSAGES.get(exc.status_code, "Erro na requisição.")
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
