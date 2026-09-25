"""Webflow MCP server via stdio — protocolo MCP real, sin LLM en el loop.

Este es el camino para la categoria MCP del hackathon. Vale la pena aclarar
por que es stdio y no el endpoint remoto:

  El server remoto (https://mcp.webflow.com/mcp) autentica SOLO por OAuth con
  consentimiento en navegador. No hay credencial machine-to-machine documentada,
  asi que un worker headless no puede autenticarse ahi.

  El server local (npx webflow-mcp-server) toma un token estatico por la env var
  WEBFLOW_TOKEN. La doc del CMS confirma que esas tools son headless-capable:
  "You can call them headlessly, from a server, script, or agent, without the
  Designer being open."

Forma de las tools: una sola `data_cms_tool` con parametro `action`.
Los items se crean SIEMPRE como draft; publicar es una accion separada.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .. import config
from . import PublishResult, build_field_data

log = logging.getLogger(__name__)

CMS_TOOL = "data_cms_tool"


class McpPublisher:
    name = "mcp"

    def __init__(self) -> None:
        missing = [
            var
            for var, value in (
                ("WEBFLOW_TOKEN", config.WEBFLOW_TOKEN),
                ("WEBFLOW_COLLECTION_ID", config.WEBFLOW_COLLECTION_ID),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"PUBLISHER=mcp requiere {', '.join(missing)}")

    def publish(self, audit: dict[str, Any], report_html: str) -> PublishResult:
        # El worker corre en un thread sin event loop, asi que abrimos uno propio.
        return asyncio.run(self._publish_async(audit, report_html))

    async def _publish_async(
        self, audit: dict[str, Any], report_html: str
    ) -> PublishResult:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Falta el SDK de MCP. Instala: pip install mcp"
            ) from exc

        params = StdioServerParameters(
            command=config.WEBFLOW_MCP_COMMAND,
            args=[a for a in config.WEBFLOW_MCP_ARGS.split(",") if a],
            env={"WEBFLOW_TOKEN": config.WEBFLOW_TOKEN},
        )
        field_data = build_field_data(audit, report_html)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                if log.isEnabledFor(logging.DEBUG):
                    tools = await session.list_tools()
                    log.debug("Tools MCP: %s", [t.name for t in tools.tools])

                # 1) Crear el item (queda como draft)
                created = await session.call_tool(
                    CMS_TOOL,
                    {
                        "action": "create_collection_items",
                        "collection_id": config.WEBFLOW_COLLECTION_ID,
                        "request": {"fieldData": field_data},
                    },
                )
                item_id = _extract_item_id(created)
                if not item_id:
                    raise RuntimeError(
                        f"No se pudo extraer el item id de la respuesta MCP: "
                        f"{_as_text(created)[:400]}"
                    )

                # 2) Publicarlo live (paso obligatoriamente separado)
                published = await session.call_tool(
                    CMS_TOOL,
                    {
                        "action": "publish_collection_items",
                        "collection_id": config.WEBFLOW_COLLECTION_ID,
                        "request": {"itemIds": [item_id]},
                    },
                )
                log.info(
                    "Publicado via MCP: item=%s resp=%s",
                    item_id, _as_text(published)[:200],
                )

        public_url = (
            f"{config.WEBFLOW_SITE_DOMAIN}/audit/{field_data['slug']}"
            if config.WEBFLOW_SITE_DOMAIN
            else None
        )
        return PublishResult(url=public_url, item_id=item_id, backend=self.name)


def _as_text(result: Any) -> str:
    """Concatena los bloques de texto de un CallToolResult."""
    chunks: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _extract_item_id(result: Any) -> str | None:
    """El MCP server devuelve el item creado como JSON dentro de un bloque de texto.

    La forma exacta varia entre versiones del server, asi que buscamos el id en
    los lugares donde puede venir en vez de asumir una sola estructura.
    """
    structured = getattr(result, "structuredContent", None)
    candidates: list[Any] = [structured] if structured else []

    for text in _as_text(result).splitlines():
        text = text.strip()
        if text.startswith(("{", "[")):
            try:
                candidates.append(json.loads(text))
            except json.JSONDecodeError:
                continue

    for payload in candidates:
        found = _find_id(payload)
        if found:
            return found
    return None


def _find_id(payload: Any, depth: int = 0) -> str | None:
    if depth > 6:
        return None
    if isinstance(payload, dict):
        for key in ("id", "itemId", "_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("items", "item", "result", "data", "content"):
            if key in payload:
                found = _find_id(payload[key], depth + 1)
                if found:
                    return found
        for value in payload.values():
            found = _find_id(value, depth + 1)
            if found:
                return found
    elif isinstance(payload, list):
        for entry in payload:
            found = _find_id(entry, depth + 1)
            if found:
                return found
    return None
