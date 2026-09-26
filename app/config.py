"""Configuracion por variables de entorno. Sin dependencias externas."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# --- App ---------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "smartcheck.db"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
# Regex de origenes permitidos, para cubrir un subdominio que todavia no conoces
# (ej. cualquier sitio de Webflow: ^https://[a-z0-9-]+\.webflow\.io$).
# Se combina con CORS_ORIGINS: alcanza con que matchee uno de los dos.
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX", "").strip()
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# --- Rate limiting -----------------------------------------------------------
# Los audits son lo caro: cada uno arranca un Slither. Los GET son lecturas de
# SQLite, el techo esta alto a proposito porque el frontend hace polling.
RATE_LIMIT_ENABLED = _flag("RATE_LIMIT_ENABLED", "1")
RATE_AUDITS_PER_IP = int(os.getenv("RATE_AUDITS_PER_IP", "5"))
RATE_AUDITS_GLOBAL = int(os.getenv("RATE_AUDITS_GLOBAL", "20"))
RATE_AUDITS_WINDOW = int(os.getenv("RATE_AUDITS_WINDOW", "600"))
RATE_READS_PER_IP = int(os.getenv("RATE_READS_PER_IP", "300"))
RATE_READS_WINDOW = int(os.getenv("RATE_READS_WINDOW", "60"))

# --- Analisis ----------------------------------------------------------------
SLITHER_TIMEOUT = int(os.getenv("SLITHER_TIMEOUT", "120"))
SOLC_TIMEOUT = int(os.getenv("SOLC_TIMEOUT", "180"))
DEFAULT_SOLC = os.getenv("DEFAULT_SOLC", "0.8.26")
MAX_SOURCE_BYTES = int(os.getenv("MAX_SOURCE_BYTES", str(1_000_000)))

# --- Fuentes de codigo verificado -------------------------------------------
# El endpoint viejo (/repository/contracts/...) esta muerto: 404 para todo.
SOURCIFY_V2 = os.getenv("SOURCIFY_V2", "https://sourcify.dev/server/v2")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
ETHERSCAN_BASE = os.getenv("ETHERSCAN_BASE", "https://api.etherscan.io/v2/api")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))

# Redes soportadas: slug -> chain id
NETWORKS = {
    "sepolia": 11155111,
    "base-sepolia": 84532,
    "polygon-amoy": 80002,
    "arbitrum-sepolia": 421614,
    "optimism-sepolia": 11155420,
}
DEFAULT_NETWORK = os.getenv("DEFAULT_NETWORK", "sepolia")

# --- Publisher (Webflow) -----------------------------------------------------
# "none"  -> no publica, el share link lo sirve este backend
# "rest"  -> Webflow Data API v2 directo (solo Python, sin Node)
# "mcp"   -> Webflow MCP server via stdio (requiere Node >= 22.3 en la imagen)
PUBLISHER = os.getenv("PUBLISHER", "none").strip().lower()
WEBFLOW_TOKEN = os.getenv("WEBFLOW_TOKEN", "")
WEBFLOW_SITE_ID = os.getenv("WEBFLOW_SITE_ID", "")
WEBFLOW_COLLECTION_ID = os.getenv("WEBFLOW_COLLECTION_ID", "")
WEBFLOW_SITE_DOMAIN = os.getenv("WEBFLOW_SITE_DOMAIN", "").rstrip("/")
WEBFLOW_ITEM_SLUG_PREFIX = os.getenv("WEBFLOW_ITEM_SLUG_PREFIX", "audit")
WEBFLOW_MCP_COMMAND = os.getenv("WEBFLOW_MCP_COMMAND", "npx")
WEBFLOW_MCP_ARGS = os.getenv("WEBFLOW_MCP_ARGS", "-y,webflow-mcp-server@latest")
WEBFLOW_API_BASE = os.getenv("WEBFLOW_API_BASE", "https://api.webflow.com/v2")
