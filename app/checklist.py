"""Agregacion: hallazgos crudos de Slither -> checklist de 10 categorias OWASP SCS."""

from __future__ import annotations

from typing import Any

from .mapping import (
    IMPACT_TO_SEVERITY,
    SEVERITY_ORDER,
    category_for,
)
from .taxonomy import CATEGORIES, CATEGORY_IDS, OWASP_SCS_VERSION

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_RISK = "risk"
STATUS_NA = "n/a"


def _extract_location(element: dict[str, Any]) -> dict[str, Any]:
    mapping = element.get("source_mapping") or {}
    lines = mapping.get("lines") or []
    return {
        "file": mapping.get("filename_short") or mapping.get("filename_relative"),
        "line": lines[0] if lines else None,
        "lines": lines[:20],
        "target": element.get("name"),
        "target_type": element.get("type"),
    }


def _finding_from_detector(item: dict[str, Any]) -> dict[str, Any]:
    detector = item.get("check", "unknown")
    elements = item.get("elements") or []
    location = _extract_location(elements[0]) if elements else {}
    description = (item.get("description") or "").strip()
    return {
        "detector": detector,
        "severity": IMPACT_TO_SEVERITY.get(item.get("impact", "Low"), "low"),
        "confidence": (item.get("confidence") or "").lower(),
        "explanation": description,
        "line": location.get("line"),
        "file": location.get("file"),
        "lines": location.get("lines", []),
        "target": location.get("target"),
    }


def _status_for(findings: list[dict[str, Any]], *, has_detectors: bool) -> str:
    """Regla de agregacion del spec.

    Informational/Optimization se listan pero no mueven el estado: si no, cualquier
    contrato normal queda en amarillo y el checklist pierde valor de señal.
    """
    if not has_detectors:
        return STATUS_NA
    actionable = [f for f in findings if f["severity"] != "info"]
    if not actionable:
        return STATUS_OK
    worst = max(SEVERITY_ORDER[f["severity"]] for f in actionable)
    return STATUS_RISK if worst == SEVERITY_ORDER["high"] else STATUS_WARNING


def build_checklist(slither_output: dict[str, Any]) -> dict[str, Any]:
    """Convierte el JSON de Slither en el checklist de 10 categorias."""
    detections = ((slither_output.get("results") or {}).get("detectors")) or []

    grouped: dict[str, list[dict[str, Any]]] = {cid: [] for cid in CATEGORY_IDS}
    unmapped: list[dict[str, Any]] = []
    ignored_style = 0

    for item in detections:
        category = category_for(item.get("check", ""))
        if category is None:
            ignored_style += 1
            continue
        finding = _finding_from_detector(item)
        if category == "UNMAPPED":
            unmapped.append(finding)
        else:
            grouped[category].append(finding)

    checklist: dict[str, Any] = {}
    for cid in CATEGORY_IDS:
        meta = CATEGORIES[cid]
        findings = sorted(
            grouped[cid], key=lambda f: -SEVERITY_ORDER[f["severity"]]
        )
        blind = meta.get("static_analysis_blind", False)
        status = STATUS_NA if blind else _status_for(findings, has_detectors=True)
        checklist[cid] = {
            "id": cid,
            "name": meta["name"],
            "name_en": meta["name_en"],
            "status": status,
            "summary": meta["summary"],
            "plain": meta["plain"],
            "fix": meta["fix"],
            "findings": findings,
            "finding_count": len(findings),
            "note": (
                "El analisis estatico no puede detectar esto: requiere simular "
                "composabilidad economica. Revisalo a mano con la guia de abajo."
                if blind else None
            ),
        }

    return {
        "owasp_version": OWASP_SCS_VERSION,
        "categories": checklist,
        "unmapped_findings": unmapped,
        "ignored_style_findings": ignored_style,
        "totals": summarize(checklist),
    }


def summarize(categories: dict[str, Any]) -> dict[str, Any]:
    counts = {STATUS_OK: 0, STATUS_WARNING: 0, STATUS_RISK: 0, STATUS_NA: 0}
    severities = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for entry in categories.values():
        counts[entry["status"]] += 1
        for finding in entry["findings"]:
            severities[finding["severity"]] += 1
    return {
        "by_status": counts,
        "by_severity": severities,
        "total_findings": sum(severities.values()),
        "verdict": _verdict(counts),
    }


def _verdict(counts: dict[str, int]) -> str:
    if counts[STATUS_RISK]:
        return "no-listo"
    if counts[STATUS_WARNING]:
        return "revisar"
    return "listo"


VERDICT_TEXT = {
    "no-listo": (
        "No pases a mainnet todavia. Hay al menos una categoria en riesgo alto "
        "que se puede explotar."
    ),
    "revisar": (
        "Casi listo. No hay riesgos altos, pero hay advertencias que conviene "
        "cerrar antes de mainnet."
    ),
    "listo": (
        "Slither no encontro hallazgos accionables en las categorias cubiertas. "
        "Ojo: eso no reemplaza una auditoria manual."
    ),
}
