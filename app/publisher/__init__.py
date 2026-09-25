"""Publicacion del reporte publico en Webflow CMS.

Dos implementaciones intercambiables por la env var PUBLISHER:

  none  -> no publica; el share link lo sirve este backend (default del MVP)
  rest  -> Webflow Data API v2 directo, solo Python (crea el item ya en live)
  mcp   -> Webflow MCP server via stdio, protocolo MCP real (requiere Node >= 22.3)

El contrato es el mismo para las tres: publish(audit, html) -> PublishResult.
El caller nunca sabe cual esta activa, asi que cambiar de una a otra es un
flip de env var sin tocar el worker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from .. import config

log = logging.getLogger(__name__)


@dataclass
class PublishResult:
    url: str | None
    item_id: str | None
    backend: str
    error: str | None = None


class Publisher(Protocol):
    name: str

    def publish(self, audit: dict[str, Any], report_html: str) -> PublishResult: ...


class NullPublisher:
    """Default del MVP: el share link lo sirve este backend, no Webflow."""

    name = "none"

    def publish(self, audit: dict[str, Any], report_html: str) -> PublishResult:
        url = f"{config.PUBLIC_BASE_URL}/api/audits/share/{audit['share_hash']}"
        return PublishResult(url=url, item_id=None, backend=self.name)


def get_publisher() -> Publisher:
    choice = config.PUBLISHER
    if choice == "rest":
        from .rest import RestPublisher

        return RestPublisher()
    if choice == "mcp":
        from .mcp import McpPublisher

        return McpPublisher()
    if choice not in ("none", ""):
        log.warning("PUBLISHER=%r desconocido, usando 'none'", choice)
    return NullPublisher()


def publish_report(audit: dict[str, Any], report_html: str) -> PublishResult:
    """Publica sin nunca romper el audit: un fallo de Webflow no invalida el analisis."""
    publisher = get_publisher()
    try:
        return publisher.publish(audit, report_html)
    except Exception as exc:  # noqa: BLE001 - publicar es best-effort
        log.exception("Publisher %s fallo", publisher.name)
        fallback = NullPublisher().publish(audit, report_html)
        return PublishResult(
            url=fallback.url, item_id=None, backend=publisher.name, error=str(exc)[:500]
        )


def build_field_data(audit: dict[str, Any], report_html: str) -> dict[str, Any]:
    """fieldData compartido por las dos implementaciones.

    Los slugs de los campos tienen que coincidir con la Collection de Webflow.
    Ver README > Schema de la Collection "Audits".
    """
    checklist = audit.get("checklist") or {}
    totals = checklist.get("totals", {})
    subject = audit.get("address") or audit.get("contract_name") or "contrato"
    return {
        "name": f"Auditoria {subject}"[:256],
        "slug": f"{config.WEBFLOW_ITEM_SLUG_PREFIX}-{audit['share_hash']}",
        "contract-address": audit.get("address") or "",
        "network": audit.get("network", ""),
        "verdict": totals.get("verdict", ""),
        "total-findings": totals.get("total_findings", 0),
        "analyzed-at": audit.get("created_at", ""),
        "report": report_html,
        "summary": audit.get("summary") or "",
    }
