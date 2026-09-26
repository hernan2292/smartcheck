"""API REST de SmartCheck — FastAPI.

Endpoints (alineados con el spec, seccion 5.5):
  POST /api/audits              { address, network }      -> audit por address verificada
  POST /api/audits/source       { source_code, network }  -> audit por codigo pegado
  GET  /api/audits/{id}                                   -> status + checklist
  GET  /api/audits/{id}/export?format=md|html             -> descarga del reporte
  GET  /api/audits/share/{hash}                           -> vista publica read-only
  GET  /api/taxonomy                                      -> las 10 categorias (modo explorar)
  GET  /api/networks                                      -> redes soportadas
  GET  /health
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from . import config, db, report, worker
from .ratelimit import SlidingWindow
from .taxonomy import CATEGORIES, OWASP_SCS_VERSION

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
log = logging.getLogger("smartcheck")

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    worker.requeue_stale()
    log.info(
        "SmartCheck listo. publisher=%s redes=%s",
        config.PUBLISHER, ",".join(config.NETWORKS),
    )
    yield
    worker.shutdown()


app = FastAPI(
    title="SmartCheck API",
    description="Auditor de contratos mapeado al OWASP Smart Contract Security Top 10",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    # Permite un subdominio que todavia no existe (ej. tu sitio de Webflow) sin
    # tener que saber el nombre exacto de antemano.
    allow_origin_regex=config.CORS_ORIGIN_REGEX or None,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Rate limiting -----------------------------------------------------------

_audit_limiter = SlidingWindow(
    config.RATE_AUDITS_PER_IP, config.RATE_AUDITS_WINDOW, "audits-por-ip"
)
_audit_global_limiter = SlidingWindow(
    config.RATE_AUDITS_GLOBAL, config.RATE_AUDITS_WINDOW, "audits-global"
)
_read_limiter = SlidingWindow(
    config.RATE_READS_PER_IP, config.RATE_READS_WINDOW, "lecturas-por-ip"
)


def _client_ip(request: Request) -> str:
    """IP del cliente.

    Detras de nginx, uvicorn tiene que arrancar con --proxy-headers y
    --forwarded-allow-ips para que reescriba esto desde X-Forwarded-For. Sin esos
    flags todas las requests parecen venir del proxy y comparten un solo cupo.
    """
    return request.client.host if request.client else "desconocido"


def _reject(retry_after: float, detail: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(int(retry_after))},
    )


def limit_audits(request: Request) -> None:
    """Techo para los endpoints que arrancan un Slither."""
    if not config.RATE_LIMIT_ENABLED:
        return

    wait = _audit_global_limiter.hit("global")
    if wait is not None:
        log.warning("Rate limit global alcanzado (%s)", _client_ip(request))
        raise _reject(
            wait,
            "El servicio esta recibiendo demasiados analisis en este momento. "
            f"Volvé a intentar en {int(wait)} segundos.",
        )

    wait = _audit_limiter.hit(_client_ip(request))
    if wait is not None:
        raise _reject(
            wait,
            f"Llegaste al limite de {config.RATE_AUDITS_PER_IP} analisis cada "
            f"{config.RATE_AUDITS_WINDOW // 60} minutos. "
            f"Volvé a intentar en {int(wait)} segundos.",
        )


def limit_reads(request: Request) -> None:
    """Techo laxo para las lecturas: el frontend hace polling cada 2.5s."""
    if not config.RATE_LIMIT_ENABLED:
        return
    wait = _read_limiter.hit(_client_ip(request))
    if wait is not None:
        raise _reject(wait, "Demasiadas consultas seguidas. Esperá unos segundos.")


# --- Schemas -----------------------------------------------------------------


class AddressAuditRequest(BaseModel):
    address: str = Field(..., description="Address del contrato (0x + 40 hex)")
    network: str = Field(default=config.DEFAULT_NETWORK)
    force: bool = Field(default=False, description="Ignorar el resultado cacheado")

    @field_validator("address")
    @classmethod
    def _valid_address(cls, value: str) -> str:
        value = value.strip()
        if not ADDRESS_RE.match(value):
            raise ValueError(
                "Address invalida. Tiene que ser 0x seguido de 40 caracteres hexadecimales."
            )
        return value

    @field_validator("network")
    @classmethod
    def _valid_network(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in config.NETWORKS:
            raise ValueError(
                f"Red no soportada: {value}. Disponibles: {', '.join(config.NETWORKS)}"
            )
        return value


class SourceAuditRequest(BaseModel):
    source_code: str = Field(..., min_length=20)
    network: str = Field(default=config.DEFAULT_NETWORK)

    @field_validator("source_code")
    @classmethod
    def _looks_like_solidity(cls, value: str) -> str:
        if len(value.encode("utf-8")) > config.MAX_SOURCE_BYTES:
            raise ValueError(
                f"El codigo supera el limite de {config.MAX_SOURCE_BYTES // 1000}KB"
            )
        if "contract" not in value and "library" not in value and "interface" not in value:
            raise ValueError(
                "No parece codigo Solidity: no se encontro contract, library ni interface."
            )
        return value


# --- Helpers -----------------------------------------------------------------


def _public_view(audit: dict[str, Any]) -> dict[str, Any]:
    """Proyeccion para la API: sin el JSON crudo de Slither, que es enorme."""
    return {
        "id": audit["id"],
        "status": audit["status"],
        "network": audit["network"],
        "address": audit["address"],
        "source_type": audit["source_type"],
        "contract_name": audit["contract_name"],
        "checklist": audit["checklist"],
        "summary": audit["summary"],
        "share_hash": audit["share_hash"],
        "share_url": f"{config.PUBLIC_BASE_URL}/api/audits/share/{audit['share_hash']}",
        "public_url": audit["public_url"],
        "error_message": audit["error_message"],
        "created_at": audit["created_at"],
        "updated_at": audit["updated_at"],
    }


def _require(audit: dict[str, Any] | None) -> dict[str, Any]:
    if audit is None:
        raise HTTPException(status_code=404, detail="Auditoria no encontrada")
    return audit


# --- Endpoints ---------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "publisher": config.PUBLISHER, "owasp": OWASP_SCS_VERSION}


@app.get("/api/networks", dependencies=[Depends(limit_reads)])
def networks() -> dict[str, Any]:
    return {
        "default": config.DEFAULT_NETWORK,
        "networks": [
            {"slug": slug, "chain_id": chain_id, "label": slug.replace("-", " ").title()}
            for slug, chain_id in config.NETWORKS.items()
        ],
    }


@app.get("/api/taxonomy", dependencies=[Depends(limit_reads)])
def taxonomy() -> dict[str, Any]:
    """Las 10 categorias sin datos de audit — alimenta el modo explorar (UC3)."""
    return {
        "owasp_version": OWASP_SCS_VERSION,
        "categories": [{"id": cid, **meta} for cid, meta in CATEGORIES.items()],
    }


@app.post("/api/audits", status_code=202, dependencies=[Depends(limit_audits)])
def create_address_audit(payload: AddressAuditRequest) -> dict[str, Any]:
    if not payload.force:
        cached = db.find_cached_verified(payload.network, payload.address)
        if cached:
            log.info("Cache hit para %s en %s", payload.address, payload.network)
            return {**_public_view(cached), "cached": True}

    audit = db.create_audit(
        network=payload.network, source_type="verified", address=payload.address
    )
    worker.submit(audit["id"])
    return {**_public_view(audit), "cached": False}


@app.post("/api/audits/source", status_code=202, dependencies=[Depends(limit_audits)])
def create_source_audit(payload: SourceAuditRequest) -> dict[str, Any]:
    audit = db.create_audit(
        network=payload.network, source_type="pasted", source_code=payload.source_code
    )
    worker.submit(audit["id"])
    return _public_view(audit)


@app.get("/api/audits", dependencies=[Depends(limit_reads)])
def list_audits(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {"audits": db.list_audits(limit)}


@app.get("/api/audits/{audit_id}", dependencies=[Depends(limit_reads)])
def get_audit(audit_id: str) -> dict[str, Any]:
    return _public_view(_require(db.get_audit(audit_id)))


@app.get("/api/audits/{audit_id}/raw", dependencies=[Depends(limit_reads)])
def get_raw(audit_id: str) -> dict[str, Any]:
    """JSON crudo de Slither, para debug y para el futuro UC6 (comparar versiones)."""
    audit = _require(db.get_audit(audit_id))
    return {"id": audit["id"], "raw_slither_output": audit["raw_slither_output"]}


@app.get("/api/audits/{audit_id}/export", dependencies=[Depends(limit_reads)])
def export_audit(
    audit_id: str, format: Literal["md", "html"] = Query(default="md")
):
    audit = _require(db.get_audit(audit_id))
    if audit["status"] != "done":
        raise HTTPException(
            status_code=409,
            detail=f"La auditoria todavia no esta lista (status={audit['status']})",
        )

    stem = audit["address"] or audit["contract_name"] or audit["id"][:8]
    if format == "md":
        return PlainTextResponse(
            report.to_markdown(audit),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="auditoria-{stem}.md"'},
        )
    return HTMLResponse(report.to_html(audit, standalone=True))


@app.get("/api/audits/share/{share_hash}", dependencies=[Depends(limit_reads)])
def share_view(share_hash: str, format: str = Query(default="json")):
    """Vista publica read-only (UC5). Si Webflow esta activo, el link canonico es el suyo."""
    audit = _require(db.get_by_share_hash(share_hash))
    if format == "html":
        return HTMLResponse(report.to_html(audit, standalone=True))
    return _public_view(audit)
