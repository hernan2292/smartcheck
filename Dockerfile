# SmartCheck backend — Python + Slither + solc
#
# Node NO se instala por default: solo hace falta con PUBLISHER=mcp, porque el
# Webflow MCP server es un paquete npm. Para activarlo, descomenta el bloque
# marcado mas abajo y rebuildeá.
#
# Para un droplet chico (< 1GB RAM) conviene el deploy con systemd + venv en vez
# de esta imagen: usa ~600MB menos de disco. Ver README > Deploy.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SOLC_VERSION=0.8.26

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --- Descomentar SOLO si vas a usar PUBLISHER=mcp ---------------------------
# El MCP server de Webflow requiere Node >= 22.3
# RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
#     && apt-get install -y --no-install-recommends nodejs \
#     && rm -rf /var/lib/apt/lists/*
# ---------------------------------------------------------------------------

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Usuario sin privilegios: el codigo pegado por el usuario se compila aca dentro
# (sandboxing del spec, seccion 5.8)
RUN useradd --create-home --shell /usr/sbin/nologin smartcheck \
    && mkdir -p /srv/data \
    && chown -R smartcheck:smartcheck /srv

COPY --chown=smartcheck:smartcheck app ./app

USER smartcheck
ENV HOME=/home/smartcheck \
    DB_PATH=/srv/data/smartcheck.db

# Pre-descarga del solc default para que el primer audit no pague la bajada.
# Se usa download_solc() y no `solc-select install` a proposito: solc-select baja
# con urllib y binaries.soliditylang.org responde 403 al User-Agent de Python.
# Corre como smartcheck para que el artifact quede en su ~/.solc-select.
RUN python -c "from app.analyzer import download_solc; download_solc('${SOLC_VERSION}')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health',timeout=4).status_code==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
