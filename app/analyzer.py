"""Runner de Slither: escribe los .sol a un temp dir, resuelve solc y parsea el JSON."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class AnalysisError(Exception):
    """Fallo de compilacion o de Slither."""


def detect_solc_version(sources: dict[str, str]) -> str:
    """Elige la version de solc mas alta declarada en los pragmas."""
    versions: list[tuple[int, int, int]] = []
    for code in sources.values():
        for pragma in _PRAGMA_RE.findall(code):
            versions.extend(
                (int(a), int(b), int(c)) for a, b, c in _VERSION_RE.findall(pragma)
            )
    if not versions:
        log.info("Sin pragma detectable, usando default %s", config.DEFAULT_SOLC)
        return config.DEFAULT_SOLC

    major, minor, patch = max(versions)
    # Un pragma "^0.8.0" compila con cualquier 0.8.x; usamos el default si es mas nuevo,
    # porque las versiones viejas suelen no tener build para la plataforma.
    if (major, minor) == (0, 8):
        default = _VERSION_RE.search(config.DEFAULT_SOLC)
        if default:
            d = tuple(int(x) for x in default.groups())
            if d >= (major, minor, patch):
                return config.DEFAULT_SOLC
    return f"{major}.{minor}.{patch}"


def _run(cmd: list[str], timeout: int, cwd: str | None = None) -> subprocess.CompletedProcess:
    log.info("exec: %s", " ".join(cmd))
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
    )


def ensure_solc(version: str) -> str:
    """Instala y selecciona la version con solc-select. Devuelve la version efectiva."""
    try:
        installed = _run(["solc-select", "versions"], timeout=60)
        if version not in installed.stdout:
            result = _run(["solc-select", "install", version], timeout=config.SOLC_TIMEOUT)
            if result.returncode != 0:
                log.warning(
                    "No se pudo instalar solc %s (%s), cayendo a %s",
                    version, result.stderr.strip()[:200], config.DEFAULT_SOLC,
                )
                version = config.DEFAULT_SOLC
                _run(["solc-select", "install", version], timeout=config.SOLC_TIMEOUT)
        _run(["solc-select", "use", version], timeout=60)
        return version
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise AnalysisError(f"solc-select no disponible o timeout: {exc}") from exc


def _pick_target(root: Path, sources: dict[str, str]) -> Path:
    """Elige el archivo a analizar: el mas grande que no sea una dependencia."""
    candidates = [
        p for p in sources
        if not any(dep in p.lower() for dep in ("openzeppelin", "node_modules", "lib/", "@"))
    ]
    pool = candidates or list(sources)
    target = max(pool, key=lambda p: len(sources[p]))
    return root / target


def run_slither(sources: dict[str, str]) -> tuple[dict, str]:
    """Corre Slither sobre los sources. Devuelve (json_crudo, nombre_contrato)."""
    if not sources:
        raise AnalysisError("No hay codigo fuente para analizar")

    total = sum(len(c.encode("utf-8")) for c in sources.values())
    if total > config.MAX_SOURCE_BYTES:
        raise AnalysisError(
            f"El codigo supera el limite de {config.MAX_SOURCE_BYTES // 1000}KB "
            f"({total // 1000}KB recibidos)"
        )

    version = ensure_solc(detect_solc_version(sources))

    with tempfile.TemporaryDirectory(prefix="smartcheck-") as tmp:
        root = Path(tmp)
        for rel_path, code in sources.items():
            dest = (root / rel_path).resolve()
            # Defensa contra path traversal en paths que vienen de una API externa
            if not str(dest).startswith(str(root.resolve())):
                raise AnalysisError(f"Path sospechoso en el source: {rel_path}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(code, encoding="utf-8")

        target = _pick_target(root, sources)
        cmd = [
            "slither", str(target.relative_to(root)),
            "--json", "-",
            "--solc-disable-warnings",
            "--no-fail-pedantic",
        ]
        try:
            result = _run(cmd, timeout=config.SLITHER_TIMEOUT, cwd=str(root))
        except subprocess.TimeoutExpired as exc:
            raise AnalysisError(
                f"Slither excedio el timeout de {config.SLITHER_TIMEOUT}s. "
                "El contrato puede ser muy grande."
            ) from exc

        # Slither sale con codigo != 0 cuando ENCUENTRA hallazgos: eso no es un error.
        # El error real es no poder parsear JSON de stdout.
        stdout = result.stdout.strip()
        if not stdout:
            stderr = result.stderr.strip()
            hint = ""
            if "Source file requires different compiler version" in stderr:
                hint = f" (se uso solc {version}; revisa el pragma)"
            elif "File not found" in stderr or "not found:" in stderr:
                hint = (
                    " Falta una dependencia: si el contrato importa OpenZeppelin, "
                    "pega el codigo aplanado (flattened) o usa una address verificada."
                )
            raise AnalysisError(f"Slither no produjo salida{hint}. stderr: {stderr[:600]}")

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AnalysisError(f"Salida de Slither no parseable: {stdout[:400]}") from exc

        if not payload.get("success") and not payload.get("results"):
            raise AnalysisError(f"Slither fallo: {str(payload.get('error'))[:600]}")

        return payload, target.stem
