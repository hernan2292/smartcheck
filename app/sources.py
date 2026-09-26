"""Obtencion de codigo fuente verificado: Sourcify primero, Etherscan v2 como fallback.

Dos cosas que se aprendieron a los golpes y definen este modulo:

1. El endpoint viejo de Sourcify (`/repository/contracts/{match}/{chain}/{addr}/`)
   esta muerto: devuelve 404 para TODO, incluso contratos que si estan verificados.
   Hay que usar la API v2 (`/v2/contract/{chain}/{addr}`).

2. Sourcify valida el checksum EIP-55 y rechaza con "Invalid address" cualquier
   address con mayusculas mal puestas — y varias addresses que circulan en la
   documentacion oficial de proyectos conocidos lo tienen mal. Por eso toda
   address se re-checksumea antes de consultar.

Bonus de la v2: devuelve la version exacta del compilador y el nombre del
contrato, asi no hay que adivinarlos del pragma.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx
from eth_utils import to_checksum_address

from . import config

log = logging.getLogger(__name__)


class SourceNotFound(Exception):
    """El contrato no esta verificado en ninguna de las fuentes."""


class InvalidAddress(Exception):
    """La address no es una address hexadecimal valida."""


@dataclass
class VerifiedSource:
    files: dict[str, str]
    origin: str
    compiler_version: str | None = None
    contract_name: str | None = None
    match: str | None = None
    warnings: list[str] = field(default_factory=list)


# Archivos que no aportan al analisis del contrato principal.
_SKIP_PREFIXES = ("test/", "tests/", "script/", "scripts/")
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def normalize_address(address: str) -> str:
    """Devuelve la address en su forma EIP-55 canonica.

    Se pasa por .lower() antes: to_checksum_address re-calcula el checksum sin
    validar el que venia, y asi el resultado es identico para cualquier casing de
    entrada. Sin esto, Sourcify rechaza addresses que los usuarios copian y pegan
    de documentacion oficial con el checksum mal.
    """
    try:
        return to_checksum_address(address.strip().lower())
    except Exception as exc:  # eth_utils tira varios tipos distintos
        raise InvalidAddress(f"Address invalida: {address!r}") from exc


def _normalize_path(path: str) -> str:
    """Aplana paths que vienen de una API externa, sin permitir escapar del temp dir."""
    clean = path.replace("\\", "/").lstrip("/")
    parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) if parts else "Contract.sol"


def _clean_compiler_version(raw: str | None) -> str | None:
    """'0.7.6+commit.7338295f' o 'v0.7.6+commit...' -> '0.7.6'."""
    if not raw:
        return None
    match = _VERSION_RE.search(raw)
    return match.group(1) if match else None


def fetch_from_sourcify(address: str, chain_id: int) -> VerifiedSource:
    """Sourcify API v2. Gratis, sin API key, multichain."""
    url = f"{config.SOURCIFY_V2}/contract/{chain_id}/{address}"
    try:
        resp = httpx.get(
            url,
            params={"fields": "sources,compilation"},
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise SourceNotFound(f"Sourcify no responde: {exc}") from exc

    if resp.status_code == 404:
        raise SourceNotFound("no esta verificado en Sourcify")
    if resp.status_code >= 400:
        raise SourceNotFound(f"Sourcify respondio {resp.status_code}: {resp.text[:200]}")

    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise SourceNotFound(f"Sourcify devolvio algo no-JSON: {exc}") from exc

    raw_sources = payload.get("sources") or {}
    files: dict[str, str] = {}
    for raw_path, info in raw_sources.items():
        path = _normalize_path(raw_path)
        if any(path.lower().startswith(p) for p in _SKIP_PREFIXES):
            continue
        content = info.get("content") if isinstance(info, dict) else info
        if content:
            files[path] = content

    if not files:
        raise SourceNotFound("Sourcify tiene el contrato pero no devolvio los fuentes")

    compilation = payload.get("compilation") or {}
    result = VerifiedSource(
        files=files,
        origin="sourcify",
        compiler_version=_clean_compiler_version(compilation.get("compilerVersion")),
        contract_name=compilation.get("name"),
        match=payload.get("match"),
    )
    # match == "match" (antes "partial_match") significa que el bytecode coincide
    # salvo metadata: el fuente es el correcto pero pudo compilarse con settings
    # distintos. Vale avisarlo, no descartarlo.
    if result.match and result.match != "exact_match":
        result.warnings.append(
            "Sourcify reporta una coincidencia parcial: el codigo fuente corresponde "
            "al contrato pero pudo compilarse con opciones distintas."
        )
    log.info(
        "Sourcify: %s -> %d archivos, solc %s, contrato %s (%s)",
        address, len(files), result.compiler_version, result.contract_name, result.match,
    )
    return result


def fetch_from_etherscan(address: str, chain_id: int) -> VerifiedSource:
    """Etherscan API v2 unificada (un solo endpoint multichain, requiere API key)."""
    if not config.ETHERSCAN_API_KEY:
        raise SourceNotFound("no hay fallback de Etherscan configurado en el servidor")

    params = {
        "chainid": chain_id,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": config.ETHERSCAN_API_KEY,
    }
    try:
        resp = httpx.get(config.ETHERSCAN_BASE, params=params, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise SourceNotFound(f"Etherscan no responde: {exc}") from exc

    result = payload.get("result")
    if payload.get("status") == "0" or not result or not isinstance(result, list):
        raise SourceNotFound(f"Etherscan: {payload.get('result') or payload.get('message')}")

    entry = result[0]
    raw_source = (entry.get("SourceCode") or "").strip()
    if not raw_source:
        raise SourceNotFound("no esta verificado en Etherscan")

    name = entry.get("ContractName") or "Contract"
    version = _clean_compiler_version(entry.get("CompilerVersion"))

    # Etherscan devuelve 3 formatos distintos. El doble-brace es standard-json-input.
    if raw_source.startswith("{{") and raw_source.endswith("}}"):
        parsed = json.loads(raw_source[1:-1])
        files = {
            _normalize_path(p): info.get("content", "")
            for p, info in (parsed.get("sources") or {}).items()
        }
    elif raw_source.startswith("{"):
        try:
            parsed = json.loads(raw_source)
        except json.JSONDecodeError:
            files = {f"{name}.sol": raw_source}
        else:
            sources = parsed.get("sources", parsed)
            files = {
                _normalize_path(p): info.get("content", "") if isinstance(info, dict) else str(info)
                for p, info in sources.items()
            }
    else:
        files = {f"{name}.sol": raw_source}

    files = {p: c for p, c in files.items() if c}
    if not files:
        raise SourceNotFound("Etherscan no devolvio los fuentes")

    log.info("Etherscan: %s -> %d archivos, solc %s", address, len(files), version)
    return VerifiedSource(
        files=files, origin="etherscan", compiler_version=version, contract_name=name
    )


def fetch_verified_source(address: str, network: str) -> VerifiedSource:
    """Sourcify -> Etherscan. La address se normaliza antes de cualquier consulta."""
    chain_id = config.NETWORKS.get(network)
    if chain_id is None:
        raise SourceNotFound(f"Red no soportada: {network}")

    checksummed = normalize_address(address)
    if checksummed != address:
        log.info("Address re-checksumeada: %s -> %s", address, checksummed)

    try:
        return fetch_from_sourcify(checksummed, chain_id)
    except SourceNotFound as sourcify_error:
        log.info("Sourcify miss para %s (%s), probando Etherscan", checksummed, sourcify_error)
        try:
            return fetch_from_etherscan(checksummed, chain_id)
        except SourceNotFound as etherscan_error:
            # Mensaje para el usuario: que puede hacer, no que fallo adentro.
            raise SourceNotFound(
                "No se encontro el codigo fuente verificado de este contrato. "
                "Puede que no este verificado en esta red, o que la direccion no "
                "corresponda a un contrato. Podes pegar el codigo fuente a mano "
                "en la otra pestaña."
            ) from etherscan_error
