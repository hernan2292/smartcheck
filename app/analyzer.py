"""Runner de Slither: escribe los .sol a un temp dir, resuelve solc y parsea el JSON."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);", re.IGNORECASE)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_SOLC_BINARIES = "https://binaries.soliditylang.org"


class AnalysisError(Exception):
    """Fallo de compilacion o de Slither."""


Version = tuple[int, int, int]

# Operador opcional + version. Cubre ^ ~ >= <= > < = y la version pelada.
_CONSTRAINT_RE = re.compile(r"(>=|<=|\^|~|>|<|=)?\s*(\d+)\.(\d+)\.(\d+)")


def _parse_version(text: str) -> Version | None:
    match = _VERSION_RE.search(text)
    if not match:
        return None
    a, b, c = match.groups()
    return (int(a), int(b), int(c))


def _next_patch(v: Version) -> Version:
    return (v[0], v[1], v[2] + 1)


def _next_minor(v: Version) -> Version:
    return (v[0], v[1] + 1, 0)


class SolcRange:
    """Rango de versiones aceptables: minimo inclusivo, maximo exclusivo."""

    def __init__(self, minimum: Version | None = None, maximum: Version | None = None):
        self.minimum = minimum
        self.maximum = maximum

    def tighten(self, minimum: Version | None, maximum: Version | None) -> None:
        """Intersecta con otra restriccion: el minimo mas alto y el maximo mas bajo."""
        if minimum and (self.minimum is None or minimum > self.minimum):
            self.minimum = minimum
        if maximum and (self.maximum is None or maximum < self.maximum):
            self.maximum = maximum

    def allows(self, v: Version) -> bool:
        if self.minimum and v < self.minimum:
            return False
        if self.maximum and v >= self.maximum:
            return False
        return True

    @property
    def is_open(self) -> bool:
        return self.minimum is None and self.maximum is None

    def __str__(self) -> str:
        if self.is_open:
            return "cualquiera"
        lo = ".".join(map(str, self.minimum)) if self.minimum else "*"
        hi = ".".join(map(str, self.maximum)) if self.maximum else "*"
        return f">={lo} <{hi}"


def detect_solc_range(sources: dict[str, str]) -> SolcRange:
    """Interpreta los pragmas de todos los archivos como un unico rango.

    Se intersectan las restricciones de todos los archivos: si una dependencia
    exige <0.8.0 y el contrato principal >=0.7.0, hay que compilar con 0.7.x.
    Tomar el maximo a secas (lo que haciamos antes) elegia 0.8.x y no compilaba.
    """
    allowed = SolcRange()
    for code in sources.values():
        for pragma in _PRAGMA_RE.findall(code):
            for op, a, b, c in _CONSTRAINT_RE.findall(pragma):
                v: Version = (int(a), int(b), int(c))
                if op == "^":
                    # ^0.8.20 en Solidity es >=0.8.20 <0.9.0
                    allowed.tighten(v, _next_minor(v))
                elif op == "~":
                    allowed.tighten(v, _next_minor(v))
                elif op == ">=":
                    allowed.tighten(v, None)
                elif op == ">":
                    allowed.tighten(_next_patch(v), None)
                elif op == "<":
                    allowed.tighten(None, v)
                elif op == "<=":
                    allowed.tighten(None, _next_patch(v))
                else:  # exacta ("=0.7.6" o "0.7.6")
                    allowed.tighten(v, _next_patch(v))
    return allowed


_releases_cache: dict[str, dict[str, str]] = {}


def _available_releases(platform: str) -> dict[str, str]:
    """{version: nombre_de_archivo} publicadas para la plataforma. Cacheado."""
    if platform in _releases_cache:
        return _releases_cache[platform]
    try:
        resp = httpx.get(
            f"{_SOLC_BINARIES}/{platform}/list.json",
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        releases = resp.json().get("releases") or {}
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"No se pudo consultar las versiones de solc: {exc}") from exc
    _releases_cache[platform] = releases
    return releases


def resolve_solc_version(allowed: SolcRange) -> str:
    """Elige la version publicada mas alta que satisface el rango.

    Se prefiere DEFAULT_SOLC cuando entra en el rango: ya suele estar descargado,
    asi que el audit arranca sin pagar la bajada.
    """
    default = _parse_version(config.DEFAULT_SOLC)
    if allowed.is_open:
        log.info("Sin pragma detectable, usando default %s", config.DEFAULT_SOLC)
        return config.DEFAULT_SOLC
    if default and allowed.allows(default):
        return config.DEFAULT_SOLC

    try:
        releases = _available_releases(_solc_platform())
    except AnalysisError:
        # Sin red no podemos elegir con criterio. Si el default no entra en el
        # rango, decirlo claro es mejor que compilar con la version equivocada.
        raise AnalysisError(
            f"El contrato exige solc {allowed} y no se pudo consultar la lista de "
            f"versiones publicadas para elegir una compatible."
        ) from None

    candidates = sorted(
        (v for v in (_parse_version(name) for name in releases) if v and allowed.allows(v)),
        reverse=True,
    )
    if not candidates:
        raise AnalysisError(
            f"Ninguna version publicada de solc satisface el pragma ({allowed})."
        )
    chosen = ".".join(map(str, candidates[0]))
    log.info("Pragma %s -> solc %s", allowed, chosen)
    return chosen


def _run(
    cmd: list[str],
    timeout: int,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    log.info("exec: %s", " ".join(cmd))
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env, check=False
    )


def _scripts_dir() -> Path:
    """Directorio de ejecutables del interprete actual (el bin/ del venv).

    Ahi viven `slither` y el shim `solc` que instala solc-select. No se puede
    confiar en el PATH heredado: systemd arranca el servicio con un PATH minimo
    que no lo incluye.
    """
    return Path(sys.executable).parent


def _find_executable(name: str) -> str:
    candidate = _scripts_dir() / (f"{name}.exe" if os.name == "nt" else name)
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise AnalysisError(
        f"No se encontro el ejecutable '{name}'. "
        f"Revisá que el entorno tenga instalado slither-analyzer."
    )


def _subprocess_env(version: str) -> dict[str, str]:
    """Env para el subprocess de slither.

    Dos cosas importan aca:
    - SOLC_VERSION: solc-select la lee antes de su archivo global-version, asi que
      la version viaja por el env en vez de mutar estado compartido con
      `solc-select use` (que seria una race con MAX_WORKERS > 1).
    - PATH: slither invoca `solc` por nombre, y ese shim esta en el bin del venv.
    """
    env = {**os.environ, "SOLC_VERSION": version}
    env["PATH"] = os.pathsep.join([str(_scripts_dir()), env.get("PATH", "")]).rstrip(os.pathsep)
    return env


def _solc_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux-amd64"
    if sys.platform == "darwin":
        return "macosx-amd64"
    if sys.platform in ("win32", "cygwin"):
        return "windows-amd64"
    raise AnalysisError(f"Plataforma sin binarios de solc publicados: {sys.platform}")


def _solc_select_dir() -> Path:
    """Replica como solc-select resuelve su directorio: VIRTUAL_ENV si esta, si no ~."""
    venv = os.environ.get("VIRTUAL_ENV")
    return (Path(venv) if venv else Path.home()) / ".solc-select"


def _artifact_path(version: str) -> Path:
    return _solc_select_dir() / "artifacts" / f"solc-{version}" / f"solc-{version}"


def download_solc(version: str) -> Path:
    """Baja el binario de solc respetando el layout que solc-select espera.

    No usamos `solc-select install` a proposito: descarga con urllib, y
    binaries.soliditylang.org devuelve 403 al User-Agent de Python
    (`Python-urllib/3.x`). httpx pasa sin problema.
    """
    target = _artifact_path(version)
    if target.exists():
        return target

    platform = _solc_platform()
    releases = _available_releases(platform)
    filename = releases.get(version)
    if not filename:
        raise AnalysisError(f"solc {version} no esta publicado para {platform}")

    try:
        binary = httpx.get(
            f"{_SOLC_BINARIES}/{platform}/{filename}",
            timeout=config.SOLC_TIMEOUT,
            follow_redirects=True,
        )
        binary.raise_for_status()
    except httpx.HTTPError as exc:
        raise AnalysisError(f"Fallo la descarga de solc {version}: {exc}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atomica: si dos workers bajan la misma version a la vez, ninguno
    # deja un binario a medio escribir que el otro intente ejecutar.
    tmp = target.with_suffix(".part")
    tmp.write_bytes(binary.content)
    tmp.chmod(0o755)
    tmp.replace(target)
    log.info("solc %s descargado (%d KB)", version, len(binary.content) // 1024)
    return target


def ensure_solc(version: str) -> str:
    """Garantiza que el binario de solc este disponible. Devuelve la version efectiva."""
    candidates = [version]
    if version != config.DEFAULT_SOLC:
        candidates.append(config.DEFAULT_SOLC)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            download_solc(candidate)
            return candidate
        except AnalysisError as exc:
            last_error = exc
            log.warning("solc %s no disponible: %s", candidate, exc)

    raise AnalysisError(f"No se pudo obtener ningun solc usable: {last_error}")


def _solc_compile_error(target: Path, root: Path, version: str) -> str:
    """Corre solc aparte para conseguir el error de compilacion real.

    Hace falta porque `slither --json -` no imprime NADA cuando la compilacion
    falla: sale con exit 1, stdout vacio y stderr vacio. Sin esto el usuario que
    pega codigo con un typo recibe un mensaje que no dice nada.
    solc, en cambio, da el error con archivo, linea, columna y un caret.
    """
    try:
        result = _run(
            [_find_executable("solc"), str(target.relative_to(root))],
            timeout=config.SOLC_TIMEOUT,
            cwd=str(root),
            env=_subprocess_env(version),
        )
    except (subprocess.TimeoutExpired, AnalysisError) as exc:
        log.warning("No se pudo obtener el error de solc: %s", exc)
        return ""
    # solc escribe los errores en stderr, pero no siempre
    return (result.stderr.strip() or result.stdout.strip())[:1500]


def _explain_failure(
    result: subprocess.CompletedProcess, target: Path, root: Path, version: str
) -> AnalysisError:
    """Arma el mensaje de error mas util que se pueda para un fallo de Slither."""
    detail = _solc_compile_error(target, root, version)
    combined = f"{result.stderr}\n{detail}"

    if "Source file requires different compiler version" in combined:
        return AnalysisError(
            f"El contrato no compila con solc {version}. Revisá el pragma:\n\n{detail}"
        )
    if "not found" in combined.lower() or "File outside allowed directories" in combined:
        return AnalysisError(
            "Falta una dependencia que el contrato importa. Si usa OpenZeppelin, "
            "pegá el codigo aplanado (flattened) o audita una address verificada, "
            f"que trae el arbol completo.\n\n{detail}"
        )
    if detail:
        return AnalysisError(f"El contrato no compila con solc {version}:\n\n{detail}")

    stderr = result.stderr.strip()
    return AnalysisError(
        "Slither no produjo resultados y el compilador no reporto el motivo."
        + (f"\n\n{stderr[:600]}" if stderr else "")
    )


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

    version = ensure_solc(resolve_solc_version(detect_solc_range(sources)))

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
            _find_executable("slither"), str(target.relative_to(root)),
            "--json", "-",
            "--solc-disable-warnings",
            "--no-fail-pedantic",
        ]
        try:
            result = _run(
                cmd,
                timeout=config.SLITHER_TIMEOUT,
                cwd=str(root),
                env=_subprocess_env(version),
            )
        except subprocess.TimeoutExpired as exc:
            raise AnalysisError(
                f"Slither excedio el timeout de {config.SLITHER_TIMEOUT}s. "
                "El contrato puede ser muy grande."
            ) from exc

        # Slither sale con codigo != 0 cuando ENCUENTRA hallazgos: eso no es un error.
        # El error real es no poder parsear JSON de stdout.
        stdout = result.stdout.strip()
        if not stdout:
            raise _explain_failure(result, target, root, version)

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AnalysisError(f"Salida de Slither no parseable: {stdout[:400]}") from exc

        if not payload.get("success") and not payload.get("results"):
            raise AnalysisError(f"Slither fallo: {str(payload.get('error'))[:600]}")

        return payload, target.stem
