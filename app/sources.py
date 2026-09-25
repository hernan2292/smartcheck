"""Obtencion de codigo fuente verificado: Sourcify primero, Etherscan v2 como fallback."""

from __future__ import annotations

import json
import logging

import httpx

from . import config

log = logging.getLogger(__name__)


class SourceNotFound(Exception):
    """El contrato no esta verificado en ninguna de las fuentes."""


class NotAContract(Exception):
    """La address es una EOA, no un contrato (caso borde del spec)."""


# Archivos que no aportan al analisis del contrato principal.
_SKIP_PREFIXES = ("test/", "tests/", "script/", "scripts/")


def _normalize_path(path: str) -> str:
    """Sourcify devuelve paths absolutos o con prefijos raros; los aplanamos de forma segura."""
    clean = path.replace("\\", "/").lstrip("/")
    parts = [p for p in clean.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) if parts else "Contract.sol"


def fetch_from_sourcify(address: str, chain_id: int) -> dict[str, str]:
    """Devuelve {path: contenido}. Sourcify es gratis y sin API key."""
    # full_match tiene prioridad sobre partial_match
    for match in ("full_match", "partial_match"):
        url = f"{config.SOURCIFY_BASE}/repository/contracts/{match}/{chain_id}/{address}/metadata.json"
        try:
            resp = httpx.get(url, timeout=config.HTTP_TIMEOUT, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("Sourcify no responde (%s): %s", match, exc)
            continue
        if resp.status_code != 200:
            continue

        try:
            metadata = resp.json()
        except json.JSONDecodeError:
            continue

        files: dict[str, str] = {}
        for raw_path, info in (metadata.get("sources") or {}).items():
            path = _normalize_path(raw_path)
            if any(path.lower().startswith(p) for p in _SKIP_PREFIXES):
                continue
            if "content" in info:
                files[path] = info["content"]
            else:
                # Sourcify guarda los .sol al lado del metadata cuando no inlinea el content
                file_url = (
                    f"{config.SOURCIFY_BASE}/repository/contracts/{match}/"
                    f"{chain_id}/{address}/sources/{raw_path.lstrip('/')}"
                )
                try:
                    file_resp = httpx.get(file_url, timeout=config.HTTP_TIMEOUT, follow_redirects=True)
                    if file_resp.status_code == 200:
                        files[path] = file_resp.text
                except httpx.HTTPError:
                    continue
        if files:
            log.info("Sourcify %s: %d archivos para %s", match, len(files), address)
            return files
    raise SourceNotFound(f"Sourcify no tiene {address} verificado en chain {chain_id}")


def fetch_from_etherscan(address: str, chain_id: int) -> dict[str, str]:
    """Etherscan API v2 unificada (un solo endpoint multichain, requiere API key)."""
    if not config.ETHERSCAN_API_KEY:
        raise SourceNotFound("ETHERSCAN_API_KEY no configurada, no hay fallback disponible")

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
        raise SourceNotFound(f"{address} no esta verificado en Etherscan")

    name = entry.get("ContractName") or "Contract"

    # Etherscan devuelve 3 formatos distintos. El doble-brace es standard-json-input.
    if raw_source.startswith("{{") and raw_source.endswith("}}"):
        parsed = json.loads(raw_source[1:-1])
        return {
            _normalize_path(p): info.get("content", "")
            for p, info in (parsed.get("sources") or {}).items()
        }
    if raw_source.startswith("{"):
        try:
            parsed = json.loads(raw_source)
        except json.JSONDecodeError:
            return {f"{name}.sol": raw_source}
        sources = parsed.get("sources", parsed)
        return {
            _normalize_path(p): info.get("content", "") if isinstance(info, dict) else str(info)
            for p, info in sources.items()
        }
    return {f"{name}.sol": raw_source}


def fetch_verified_source(address: str, network: str) -> tuple[dict[str, str], str]:
    """Devuelve (archivos, fuente_usada). Sourcify -> Etherscan."""
    chain_id = config.NETWORKS.get(network)
    if chain_id is None:
        raise SourceNotFound(f"Red no soportada: {network}")

    try:
        return fetch_from_sourcify(address, chain_id), "sourcify"
    except SourceNotFound as sourcify_error:
        log.info("Sourcify miss para %s, probando Etherscan", address)
        try:
            return fetch_from_etherscan(address, chain_id), "etherscan"
        except SourceNotFound as etherscan_error:
            raise SourceNotFound(
                f"No se encontro codigo verificado. Sourcify: {sourcify_error}. "
                f"Etherscan: {etherscan_error}. "
                "Podes pegar el codigo fuente a mano."
            ) from etherscan_error
