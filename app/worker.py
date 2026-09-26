"""Cola in-process con ThreadPoolExecutor.

Slither es un subprocess, asi que un thread pool alcanza y perfecto: no hay GIL
que estorbe mientras el proceso hijo corre. Sin Redis ni Celery para el MVP.

Limitacion conocida: si el proceso se reinicia, los audits en 'processing'
quedan huerfanos. `requeue_stale()` los marca como error al arrancar.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from . import analyzer, config, db, report, sources
from .checklist import build_checklist
from .publisher import publish_report

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(
    max_workers=config.MAX_WORKERS, thread_name_prefix="audit"
)


def submit(audit_id: str) -> None:
    _executor.submit(_run_audit, audit_id)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)


def requeue_stale() -> None:
    """Al arrancar, cierra los audits que quedaron colgados de un reinicio."""
    with db.connect() as conn:
        stale = conn.execute(
            "SELECT id FROM audits WHERE status IN ('pending','processing')"
        ).fetchall()
    for row in stale:
        db.update_audit(
            row["id"],
            status="error",
            error_message="El analisis se interrumpio por un reinicio del servidor. Volvé a correrlo.",
        )
    if stale:
        log.warning("Se cerraron %d audits huerfanos", len(stale))


def _run_audit(audit_id: str) -> None:
    audit = db.get_audit(audit_id)
    if audit is None:
        log.error("Audit %s no existe", audit_id)
        return

    db.update_audit(audit_id, status="processing")
    log.info("Audit %s: arrancando (%s)", audit_id, audit["source_type"])

    try:
        # 1. Conseguir el codigo fuente
        solc_version = None
        declared_name = None
        if audit["source_type"] == "verified":
            verified = sources.fetch_verified_source(audit["address"], audit["network"])
            files = verified.files
            solc_version = verified.compiler_version
            declared_name = verified.contract_name
            log.info(
                "Audit %s: source desde %s (%d archivos, solc %s, contrato %s, match %s)",
                audit_id, verified.origin, len(files), solc_version,
                declared_name, verified.match,
            )
            for aviso in verified.warnings:
                log.info("Audit %s: %s", audit_id, aviso)
            db.update_audit(
                audit_id, source_code="\n\n".join(files.values())[: config.MAX_SOURCE_BYTES]
            )
        else:
            files = {"Contract.sol": audit["source_code"] or ""}

        # 2. Correr Slither. Cuando la fuente de verificacion reporta la version
        # exacta de solc y el nombre del contrato, se usan: son datos duros, no
        # inferencias del pragma ni heuristicas de tamaño de archivo.
        raw_output, contract_name = analyzer.run_slither(
            files, solc_version=solc_version, contract_name=declared_name
        )

        # 3. Mapear a las 10 categorias OWASP
        checklist = build_checklist(raw_output)

        db.update_audit(
            audit_id,
            raw_slither_output=raw_output,
            checklist=checklist,
            contract_name=contract_name,
            status="done",
            error_message=None,
        )

        # 4. Publicar el reporte publico (best-effort, nunca invalida el audit)
        fresh = db.get_audit(audit_id)
        if fresh:
            summary = report.build_plain_summary(fresh)
            db.update_audit(audit_id, summary=summary)
            fresh["summary"] = summary

            result = publish_report(fresh, report.to_html(fresh))
            db.update_audit(
                audit_id, public_url=result.url, webflow_item_id=result.item_id
            )
            if result.error:
                log.warning("Audit %s: publisher fallo: %s", audit_id, result.error)

        log.info("Audit %s: listo", audit_id)

    except (sources.SourceNotFound, analyzer.AnalysisError) as exc:
        log.info("Audit %s: fallo esperado: %s", audit_id, exc)
        db.update_audit(audit_id, status="error", error_message=str(exc))
    except Exception as exc:  # noqa: BLE001 - el worker nunca debe morir en silencio
        log.exception("Audit %s: fallo inesperado", audit_id)
        db.update_audit(
            audit_id, status="error", error_message=f"Error inesperado: {exc}"[:1000]
        )
