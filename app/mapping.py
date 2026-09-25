"""Mapeo detector de Slither -> categoria OWASP SCS Top 10.

Esto no existe publicado en ningun lado, es el diferencial del producto.
Cada detector cae en exactamente una categoria. Los detectores que Slither
reporta y no estan aca caen en UNMAPPED y se muestran aparte, para que
nunca se pierda un hallazgo silenciosamente.

Referencia de detectores: `slither --list-detectors`
"""

DETECTOR_TO_CATEGORY = {
    # --- SC01 Access Control -------------------------------------------------
    "suicidal": "SC01",
    "unprotected-upgrade": "SC01",
    "arbitrary-send-eth": "SC01",
    "arbitrary-send-erc20": "SC01",
    "arbitrary-send-erc20-permit": "SC01",
    "tx-origin": "SC01",
    "protected-vars": "SC01",
    "incorrect-modifier": "SC01",
    "controlled-delegatecall": "SC01",
    "delegatecall-loop": "SC01",
    "shadowing-state": "SC01",
    "shadowing-abstract": "SC01",
    "reused-constructor": "SC01",
    "multiple-constructors": "SC01",
    "function-init-state": "SC01",
    "constant-function-asm": "SC01",
    "constant-function-state": "SC01",
    # --- SC02 Price Oracle Manipulation --------------------------------------
    "timestamp": "SC02",
    "var-read-using-this": "SC02",
    # --- SC03 Logic Errors ---------------------------------------------------
    "incorrect-equality": "SC03",
    "boolean-cst": "SC03",
    "boolean-equal": "SC03",
    "tautology": "SC03",
    "void-cst": "SC03",
    "incorrect-return": "SC03",
    "return-leave": "SC03",
    "incorrect-unary": "SC03",
    "write-after-write": "SC03",
    "dead-code": "SC03",
    "redundant-statements": "SC03",
    "assert-state-change": "SC03",
    "mapping-deletion": "SC03",
    "storage-array": "SC03",
    "array-by-reference": "SC03",
    "uninitialized-state": "SC03",
    "uninitialized-local": "SC03",
    "uninitialized-storage": "SC03",
    "uninitialized-fptr-cst": "SC03",
    "missing-inheritance": "SC03",
    "unimplemented-functions": "SC03",
    "shadowing-local": "SC03",
    "shadowing-builtin": "SC03",
    "name-reused": "SC03",
    "similar-names": "SC03",
    "domain-separator-collision": "SC03",
    "rtlo": "SC03",
    "boolean-constant-misuse": "SC03",
    # --- SC04 Lack of Input Validation ---------------------------------------
    "missing-zero-check": "SC04",
    "controlled-array-length": "SC04",
    "variable-scope": "SC04",
    "abiencoderv2-array": "SC04",
    "encode-packed-collision": "SC04",
    "enum-conversion": "SC04",
    "public-mappings-nested": "SC04",
    # --- SC05 Reentrancy -----------------------------------------------------
    "reentrancy-eth": "SC05",
    "reentrancy-no-eth": "SC05",
    "reentrancy-benign": "SC05",
    "reentrancy-events": "SC05",
    "reentrancy-unlimited-gas": "SC05",
    # --- SC06 Unchecked External Calls ---------------------------------------
    "unchecked-transfer": "SC06",
    "unchecked-send": "SC06",
    "unchecked-lowlevel": "SC06",
    "unused-return": "SC06",
    "low-level-calls": "SC06",
    "return-bomb": "SC06",
    "out-of-order-retryable": "SC06",
    # --- SC07 Flash Loan Attacks --------------------------------------------
    # Sin detectores: el analisis estatico no ve composabilidad economica.
    # --- SC08 Integer Overflow / Underflow -----------------------------------
    "divide-before-multiply": "SC08",
    "incorrect-exp": "SC08",
    "incorrect-shift": "SC08",
    "solc-version": "SC08",
    "pragma": "SC08",
    # --- SC09 Insecure Randomness --------------------------------------------
    "weak-prng": "SC09",
    # --- SC10 Denial of Service ----------------------------------------------
    "calls-loop": "SC10",
    "costly-loop": "SC10",
    "msg-value-loop": "SC10",
    "locked-ether": "SC10",
    "cache-array-length": "SC10",
    # --- Ruido de estilo: se ignora, no aporta a una auditoria de seguridad ---
    # (se listan explicitamente para no mandarlos a UNMAPPED)
    "naming-convention": None,
    "external-function": None,
    "constable-states": None,
    "immutable-states": None,
    "unused-state": None,
    "assembly": None,
    "erc20-indexed": None,
    "erc20-interface": None,
    "erc721-interface": None,
    "low-level-calls-info": None,
}

# Slither impact -> severidad interna. Informational/Optimization se muestran
# pero NO cambian el estado de la categoria (si no, todo contrato queda amarillo).
IMPACT_TO_SEVERITY = {
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "Informational": "info",
    "Optimization": "info",
}

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}


def category_for(detector: str) -> str | None:
    """Devuelve la categoria SCxx, None si es ruido de estilo, 'UNMAPPED' si no se conoce."""
    if detector in DETECTOR_TO_CATEGORY:
        return DETECTOR_TO_CATEGORY[detector]
    return "UNMAPPED"
