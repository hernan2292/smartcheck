"""Generacion de reportes: Markdown y HTML.

El HTML es el que se manda a Webflow como Rich Text, por eso es inline-styled
y sin <script>: Webflow sanitiza el contenido de los campos Rich Text.
"""

from __future__ import annotations

import html
from typing import Any

from .checklist import VERDICT_TEXT

STATUS_LABEL = {
    "ok": "OK",
    "warning": "Advertencia",
    "risk": "Riesgo",
    "n/a": "No aplica",
}
STATUS_EMOJI = {"ok": "🟢", "warning": "🟡", "risk": "🔴", "n/a": "⚪"}
STATUS_COLOR = {"ok": "#16a34a", "warning": "#d97706", "risk": "#dc2626", "n/a": "#94a3b8"}
SEVERITY_LABEL = {"high": "Alta", "medium": "Media", "low": "Baja", "info": "Informativa"}


def _subject(audit: dict[str, Any]) -> str:
    if audit.get("address"):
        return f"{audit['address']} ({audit['network']})"
    return f"{audit.get('contract_name') or 'Contrato'} (codigo pegado)"


def to_markdown(audit: dict[str, Any]) -> str:
    checklist = audit.get("checklist") or {}
    categories = checklist.get("categories", {})
    totals = checklist.get("totals", {})
    verdict = totals.get("verdict", "revisar")

    lines = [
        f"# Auditoria OWASP SCS Top 10 — {_subject(audit)}",
        "",
        f"- **Veredicto**: {verdict.upper()} — {VERDICT_TEXT.get(verdict, '')}",
        f"- **Analizado**: {audit.get('created_at', '')}",
        f"- **Taxonomia**: OWASP Smart Contract Security Top 10 ({checklist.get('owasp_version')})",
        f"- **Motor**: Slither (analisis estatico)",
        f"- **Hallazgos accionables**: {totals.get('total_findings', 0)}",
        "",
        "## Resumen por categoria",
        "",
        "| # | Categoria | Estado | Hallazgos |",
        "|---|-----------|--------|-----------|",
    ]
    for cid, entry in categories.items():
        lines.append(
            f"| {cid} | {entry['name']} | {STATUS_EMOJI[entry['status']]} "
            f"{STATUS_LABEL[entry['status']]} | {entry['finding_count']} |"
        )

    lines += ["", "## Detalle", ""]
    for cid, entry in categories.items():
        lines += [
            f"### {cid} — {entry['name']} ({STATUS_LABEL[entry['status']]})",
            "",
            f"_{entry['name_en']}_",
            "",
            f"**Que es:** {entry['plain']}",
            "",
        ]
        if entry.get("note"):
            lines += [f"> {entry['note']}", ""]
        if entry["findings"]:
            lines.append("**Hallazgos:**")
            lines.append("")
            for finding in entry["findings"]:
                loc = f" — linea {finding['line']}" if finding.get("line") else ""
                lines.append(
                    f"- `{finding['detector']}` "
                    f"(severidad {SEVERITY_LABEL[finding['severity']]}){loc}"
                )
                if finding.get("explanation"):
                    for para in finding["explanation"].split("\n"):
                        if para.strip():
                            lines.append(f"  > {para.strip()}")
            lines.append("")
        else:
            lines += ["Sin hallazgos en esta categoria.", ""]
        lines += [f"**Como se arregla:** {entry['fix']}", ""]

    unmapped = checklist.get("unmapped_findings") or []
    if unmapped:
        lines += [
            "## Hallazgos sin categoria OWASP",
            "",
            "Detectores de Slither que todavia no estan mapeados a una categoria:",
            "",
        ]
        for finding in unmapped:
            lines.append(
                f"- `{finding['detector']}` (severidad {SEVERITY_LABEL[finding['severity']]})"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "_Generado por SmartCheck. El analisis estatico complementa, no reemplaza, "
        "una auditoria manual._",
    ]
    return "\n".join(lines)


def to_html(audit: dict[str, Any], *, standalone: bool = False) -> str:
    """HTML del reporte. `standalone=True` envuelve en un documento completo."""
    checklist = audit.get("checklist") or {}
    categories = checklist.get("categories", {})
    totals = checklist.get("totals", {})
    verdict = totals.get("verdict", "revisar")
    esc = html.escape

    parts = [
        f'<h1 style="margin:0 0 8px">Auditoria OWASP SCS Top 10</h1>',
        f'<p style="color:#64748b;margin:0 0 20px">{esc(_subject(audit))}</p>',
        f'<div style="padding:16px;border-radius:8px;background:#f1f5f9;margin-bottom:24px">'
        f'<strong style="text-transform:uppercase">{esc(verdict)}</strong> — '
        f'{esc(VERDICT_TEXT.get(verdict, ""))}</div>',
        '<table style="width:100%;border-collapse:collapse;margin-bottom:32px">',
        '<thead><tr style="text-align:left;border-bottom:2px solid #e2e8f0">'
        "<th>#</th><th>Categoria</th><th>Estado</th><th>Hallazgos</th></tr></thead><tbody>",
    ]
    for cid, entry in categories.items():
        color = STATUS_COLOR[entry["status"]]
        parts.append(
            f'<tr style="border-bottom:1px solid #f1f5f9">'
            f"<td><code>{cid}</code></td><td>{esc(entry['name'])}</td>"
            f'<td><span style="color:{color};font-weight:600">'
            f"{STATUS_EMOJI[entry['status']]} {STATUS_LABEL[entry['status']]}</span></td>"
            f"<td>{entry['finding_count']}</td></tr>"
        )
    parts.append("</tbody></table>")

    for cid, entry in categories.items():
        color = STATUS_COLOR[entry["status"]]
        parts += [
            f'<section style="margin-bottom:28px;padding-left:12px;border-left:4px solid {color}">',
            f"<h2 style=\"margin:0 0 4px\">{cid} — {esc(entry['name'])}</h2>",
            f'<p style="color:{color};font-weight:600;margin:0 0 12px">'
            f"{STATUS_LABEL[entry['status']]}</p>",
            f"<p>{esc(entry['plain'])}</p>",
        ]
        if entry.get("note"):
            parts.append(
                f'<p style="padding:10px;background:#f8fafc;border-radius:6px;'
                f'color:#475569"><em>{esc(entry["note"])}</em></p>'
            )
        if entry["findings"]:
            parts.append("<ul>")
            for finding in entry["findings"]:
                loc = f" — linea {finding['line']}" if finding.get("line") else ""
                parts.append(
                    f"<li><code>{esc(finding['detector'])}</code> "
                    f"(severidad {SEVERITY_LABEL[finding['severity']]}){esc(loc)}"
                )
                if finding.get("explanation"):
                    parts.append(
                        f'<br><span style="color:#475569">'
                        f"{esc(finding['explanation'][:800])}</span>"
                    )
                parts.append("</li>")
            parts.append("</ul>")
        parts += [
            f'<p><strong>Como se arregla:</strong> {esc(entry["fix"])}</p>',
            "</section>",
        ]

    body = "\n".join(parts)
    if not standalone:
        return body

    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Auditoria — {esc(_subject(audit))}</title></head>"
        '<body style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        'max-width:860px;margin:0 auto;padding:32px 20px;color:#0f172a;line-height:1.6">'
        f"{body}</body></html>"
    )


def build_plain_summary(audit: dict[str, Any]) -> str:
    """Resumen corto en texto. Es el placeholder determinista del resumen ejecutivo.

    Si mas adelante activas el resumen con LLM, este sigue siendo el fallback
    cuando la API falla (ver README > Resumen ejecutivo opcional).
    """
    checklist = audit.get("checklist") or {}
    totals = checklist.get("totals", {})
    by_status = totals.get("by_status", {})
    verdict = totals.get("verdict", "revisar")
    categories = checklist.get("categories", {})

    risky = [f"{cid} ({e['name']})" for cid, e in categories.items() if e["status"] == "risk"]
    warned = [f"{cid} ({e['name']})" for cid, e in categories.items() if e["status"] == "warning"]

    chunks = [VERDICT_TEXT.get(verdict, "")]
    if risky:
        chunks.append(f"En riesgo alto: {', '.join(risky)}.")
    if warned:
        chunks.append(f"Con advertencias: {', '.join(warned)}.")
    chunks.append(
        f"{by_status.get('ok', 0)} de 10 categorias sin hallazgos, "
        f"{by_status.get('n/a', 0)} fuera del alcance del analisis estatico."
    )
    return " ".join(c for c in chunks if c)
