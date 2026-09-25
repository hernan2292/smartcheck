"""Webflow Data API v2 directo. Solo Python, sin Node en la imagen.

Ventaja sobre MCP: el endpoint /items/live crea el item YA publicado en un
solo call, sin el paso extra de publish. Es el camino confiable del MVP.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .. import config
from . import PublishResult, build_field_data

log = logging.getLogger(__name__)


class RestPublisher:
    name = "rest"

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
            raise RuntimeError(f"PUBLISHER=rest requiere {', '.join(missing)}")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {config.WEBFLOW_TOKEN}",
            "accept-version": "2.0.0",
            "Content-Type": "application/json",
        }

    def publish(self, audit: dict[str, Any], report_html: str) -> PublishResult:
        field_data = build_field_data(audit, report_html)
        url = (
            f"{config.WEBFLOW_API_BASE}/collections/"
            f"{config.WEBFLOW_COLLECTION_ID}/items/live"
        )
        payload = {"isArchived": False, "isDraft": False, "fieldData": field_data}

        resp = httpx.post(
            url, json=payload, headers=self._headers, timeout=config.HTTP_TIMEOUT
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Webflow {resp.status_code}: {resp.text[:400]}")

        body = resp.json()
        item_id = body.get("id") or (body.get("items") or [{}])[0].get("id")
        slug = field_data["slug"]
        public_url = (
            f"{config.WEBFLOW_SITE_DOMAIN}/audit/{slug}"
            if config.WEBFLOW_SITE_DOMAIN
            else None
        )
        log.info("Publicado en Webflow (rest): item=%s slug=%s", item_id, slug)
        return PublishResult(url=public_url, item_id=item_id, backend=self.name)
