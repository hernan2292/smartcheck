"""Persistencia con sqlite3 de stdlib. Una tabla, sin ORM."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id                 TEXT PRIMARY KEY,
    network            TEXT NOT NULL,
    address            TEXT,
    source_type        TEXT NOT NULL CHECK (source_type IN ('verified','pasted')),
    source_code        TEXT,
    contract_name      TEXT,
    status             TEXT NOT NULL CHECK (status IN ('pending','processing','done','error')),
    raw_slither_output TEXT,
    checklist          TEXT,
    summary            TEXT,
    share_hash         TEXT NOT NULL UNIQUE,
    public_url         TEXT,
    webflow_item_id    TEXT,
    error_message      TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_share_hash ON audits(share_hash);
CREATE INDEX IF NOT EXISTS idx_audits_address ON audits(network, address);
CREATE INDEX IF NOT EXISTS idx_audits_created ON audits(created_at DESC);
"""

_JSON_FIELDS = ("raw_slither_output", "checklist")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    try:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    except (OSError, sqlite3.OperationalError) as exc:
        # El error crudo de sqlite ("unable to open database file") no dice nada
        # util. En el deploy esto pasa casi siempre por el volumen mal montado.
        raise RuntimeError(
            f"No se pudo abrir la base en DB_PATH={config.DB_PATH!r}: {exc}. "
            "Revisá que el directorio exista y sea escribible "
            "(en Docker, que el volumen este montado)."
        ) from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for field in _JSON_FIELDS:
        if out.get(field):
            try:
                out[field] = json.loads(out[field])
            except json.JSONDecodeError:
                out[field] = None
    return out


def create_audit(
    *,
    network: str,
    source_type: str,
    address: str | None = None,
    source_code: str | None = None,
) -> dict[str, Any]:
    audit_id = str(uuid.uuid4())
    share_hash = uuid.uuid4().hex[:12]
    ts = _now()
    with _lock, connect() as conn:
        conn.execute(
            """INSERT INTO audits
               (id, network, address, source_type, source_code, status, share_hash,
                created_at, updated_at)
               VALUES (?,?,?,?,?,'pending',?,?,?)""",
            (audit_id, network, address, source_type, source_code, share_hash, ts, ts),
        )
    return get_audit(audit_id)  # type: ignore[return-value]


def update_audit(audit_id: str, **fields: Any) -> None:
    if not fields:
        return
    for field in _JSON_FIELDS:
        if field in fields and not isinstance(fields[field], (str, type(None))):
            fields[field] = json.dumps(fields[field], ensure_ascii=False)
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE audits SET {cols} WHERE id = ?", (*fields.values(), audit_id))


def get_audit(audit_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row_to_dict(conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone())


def get_by_share_hash(share_hash: str) -> dict[str, Any] | None:
    with connect() as conn:
        return _row_to_dict(
            conn.execute("SELECT * FROM audits WHERE share_hash = ?", (share_hash,)).fetchone()
        )


def find_cached_verified(network: str, address: str) -> dict[str, Any] | None:
    """Cache por address para no re-pedir el source ya auditado (caso borde del spec)."""
    with connect() as conn:
        return _row_to_dict(
            conn.execute(
                """SELECT * FROM audits
                   WHERE network = ? AND lower(address) = lower(?) AND status = 'done'
                   ORDER BY created_at DESC LIMIT 1""",
                (network, address),
            ).fetchone()
        )


def list_audits(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, network, address, source_type, contract_name, status,
                      share_hash, public_url, created_at
               FROM audits ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
