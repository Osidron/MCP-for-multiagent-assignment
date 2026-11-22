"""Official SDK 2.x low-level server. stdout is reserved for MCP."""
import argparse
import asyncio
from dataclasses import asdict
import json
import logging
import sys
from uuid import UUID

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import Field, ValidationError

from .calculators import Input, METHODS, calculate, catalog
from drug_search import coordinator, dailymed, fda
from drug_search.models import DailyCandidate
from drug_search.translation import translate_query


class Query(Input):
    query: str = Field(min_length=1, max_length=100, description="Название препарата на русском или английском")


class Selected(Input):
    query: str = Field(min_length=1, max_length=100, description="Английский запрос из поиска")
    source: str = Field(pattern="^(DailyMed|Drugs@FDA)$", description="DailyMed или Drugs@FDA")
    identifier: str = Field(min_length=1, max_length=100, description="set_id DailyMed или номер заявки FDA")
    product_name: str = Field(default="", max_length=200, description="Точное имя выбранного продукта FDA")
    product_index: int = Field(default=0, ge=0, le=1000, description="Индекс кандидата FDA для выбора формы")


MODELS = {k: v[0] for k, v in METHODS.items()} | {
    "list_calculators": Input, "search_medications": Query,
    "search_dailymed": Query, "search_fda": Query, "get_contraindications": Selected,
}
DESCRIPTIONS = {
    "list_calculators": "Каталог: методики, параметры, единицы, границы и источники",
    "search_medications": "Фармакология · поиск противопоказаний DailyMed + Drugs@FDA с переводом",
    "search_dailymed": "Фармакология · поиск кандидатов DailyMed",
    "search_fda": "Фармакология · поиск кандидатов Drugs@FDA",
    "get_contraindications": "Фармакология · выбранная инструкция, версии и сопоставление документов",
} | {k: f"{v[2]} · {v[1]}. {v[4]}" for k, v in METHODS.items()}


def drug_operation(name: str, args: dict) -> dict:
    if name != "get_contraindications":
        query = translate_query(" ".join(args["query"].split()))
        if not query:
            raise ValueError("Введите название препарата")
        if name == "search_medications":
            return {"query": query, **asdict(coordinator.search(query))}
        return {"query": query, **asdict((dailymed if name == "search_dailymed" else fda).search(query))}
    x = Selected.model_validate(args)
    if x.source == "DailyMed":
        candidate = DailyCandidate(str(UUID(x.identifier)), "", "", "")
        return asdict(coordinator.for_daily(candidate, fda.search(x.query)))
    candidates = fda.search(x.query)
    if x.product_index >= len(candidates.items):
        raise ValueError("Выдача источника изменилась. Повторите поиск и выберите препарат.")
    selected = candidates.items[x.product_index]
    if selected.application != x.identifier or selected.product.name != x.product_name:
        raise ValueError("Выдача источника изменилась. Повторите выбор препарата.")
    return asdict(coordinator.for_fda(selected))


def create_server(network: bool = False) -> Server:
    names = list(MODELS) if network else ["bmi", "ckd_epi_2021", "cockcroft_gault", "list_calculators"]

    async def listing(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(name=name, description=DESCRIPTIONS[name],
              input_schema=MODELS[name].model_json_schema()) for name in names])

    async def calling(ctx, params):
        try:
            if params.name not in names:
                raise ValueError("Неизвестный инструмент")
            args = MODELS[params.name].model_validate(params.arguments or {}).model_dump()
            if params.name in METHODS:
                result = calculate(params.name, args)
            elif params.name == "list_calculators":
                result = catalog()
            else:
                result = await anyio.to_thread.run_sync(drug_operation, params.name, args)
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])
        except ValidationError as exc:
            details = [{"field": ".".join(map(str, e["loc"])), "reason": e["type"], "limits": e.get("ctx", {})} for e in exc.errors()]
            result = {"error": {"code": "INVALID_INPUT", "message": "Проверьте обязательные поля, типы, единицы и допустимые диапазоны.", "details": details}}
        except ValueError as exc:
            result = {"error": {"code": "INVALID_INPUT", "message": str(exc)}}
        except Exception:
            result = {"error": {"code": "SOURCE_ERROR", "message": "Источник недоступен или документ не удалось обработать. Повторите позже."}}
        return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])

    return Server("clinical-network" if network else "clinical-stdio", version="1.0.0",
                  on_list_tools=listing, on_call_tool=calling)


def network_app():
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route, Mount
    server = create_server(True)
    transport = SseServerTransport("/messages/")

    async def handle(request):
        async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(*streams, server.create_initialization_options())
        return Response()

    async def health(request):
        return JSONResponse({"service": "clinical-mcp-sse", "version": "1.0.0"})

    return Starlette(routes=[Route("/sse", handle), Mount("/messages/", app=transport.handle_post_message), Route("/health", health)])


async def stdio_main():
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--sse", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.sse:
        import uvicorn
        uvicorn.run(network_app(), host="127.0.0.1", port=args.port, log_level="warning")
    else:
        asyncio.run(stdio_main())
