# SmartCheck — backend

API que audita contratos Solidity con Slither y mapea los hallazgos al
**OWASP Smart Contract Security Top 10 (2025)**.

Este branch (`back`) es lo que va al droplet de DigitalOcean.
El frontend vive en el branch `main` y se pega en Webflow.

**Un solo lenguaje: Python.** Se fue Laravel/PHP del spec original — Slither ya
es Python, y el SDK de MCP tambien, asi que no habia razon para tener dos
runtimes orquestandose entre si.

---

## Arrancar en local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Docs interactivas en http://localhost:8000/docs

Con Docker:

```bash
cp .env.example .env
docker compose up --build
```

### Probar que funciona

```bash
# Modo explorar: las 10 categorias, sin analizar nada
curl localhost:8000/api/taxonomy

# Audit por address verificada en Sepolia
curl -X POST localhost:8000/api/audits \
  -H 'Content-Type: application/json' \
  -d '{"address":"0x...","network":"sepolia"}'

# Polling hasta status=done
curl localhost:8000/api/audits/<id>

# Reporte en Markdown
curl "localhost:8000/api/audits/<id>/export?format=md"
```

---

## Arquitectura

```
POST /api/audits
  └─> db.create_audit (status=pending)
  └─> worker.submit ──> ThreadPoolExecutor
                          1. sources.fetch_verified_source  (Sourcify -> Etherscan v2)
                          2. analyzer.run_slither           (solc-select + slither --json -)
                          3. checklist.build_checklist      (detector -> SCxx, agregacion)
                          4. report.to_html
                          5. publisher.publish_report       (none | rest | mcp)
GET /api/audits/{id}  <── el frontend hace polling cada 2.5s
```

Decisiones del MVP y por que:

| Pieza | Eleccion | Por que |
|---|---|---|
| Cola | `ThreadPoolExecutor` in-process | Slither es un subprocess, el GIL no estorba. Cero infra extra. |
| DB | SQLite + `sqlite3` stdlib | Una tabla. Un ORM seria mas codigo que el que reemplaza. |
| Publisher | `none` por default | El MVP arranca sin credenciales de Webflow. |

**Limitacion conocida:** si el proceso se reinicia, los audits en `processing`
quedan huerfanos. `worker.requeue_stale()` los marca como error al arrancar en
vez de dejarlos colgados para siempre. Si esto molesta, el siguiente paso es
Redis + un worker separado.

---

## El mapeo OWASP (el diferencial)

Vive en dos archivos:

- [`app/taxonomy.py`](app/taxonomy.py) — las 10 categorias con explicacion en
  criollo y sugerencia de fix. Fuente de verdad.
- [`app/mapping.py`](app/mapping.py) — ~75 detectores de Slither -> categoria.

Tres cosas que vale la pena saber sobre como agrega:

1. **Los hallazgos informativos no mueven el estado.** Si `Informational` y
   `Optimization` contaran como advertencia, cualquier contrato normal quedaria
   amarillo y el checklist perderia valor de señal. Se listan, no penalizan.
2. **SC07 (Flash Loans) siempre da `n/a`.** No hay detector de Slither que lo
   cubra: el analisis estatico no ve composabilidad economica. Se marca con
   `static_analysis_blind` y se muestra la guia educativa. Es mas honesto que
   inventar un verde.
3. **Ningun hallazgo se pierde.** Los detectores que no estan en el mapeo van a
   `unmapped_findings`. Los de puro estilo (`naming-convention`, etc.) estan
   mapeados a `None` a proposito y se cuentan en `ignored_style_findings`.

Version del estandar fijada en `OWASP_SCS_VERSION = "2025"` (respuesta a la
pregunta abierta #3 del spec). Si cambia, se ajusta ahi y hay que re-sincronizar
la copia del frontend en `src/taxonomy.js` del branch `main`.

---

## Publicar el reporte en Webflow

Tres modos, se cambia con la env var `PUBLISHER`:

### `none` (default)

El share link lo sirve este backend: `GET /api/audits/share/{hash}?format=html`.
Arranca sin configurar nada.

### `rest` — Webflow Data API v2

Solo Python. Usa `POST /collections/{id}/items/live`, que crea el item **ya
publicado en un solo call**. Es el camino confiable.

```
PUBLISHER=rest
WEBFLOW_TOKEN=<token del API Playground>
WEBFLOW_COLLECTION_ID=<id de la Collection "Audits">
WEBFLOW_SITE_DOMAIN=https://tu-sitio.webflow.io
```

### `mcp` — Webflow MCP server (categoria MCP del hackathon)

Protocolo MCP real, **sin LLM en el loop** — el cliente MCP es codigo
determinista. Esto importa: en un reporte de seguridad no querés un modelo
decidiendo severidades; ese dato sale de Slither.

```
PUBLISHER=mcp
WEBFLOW_TOKEN=<token del API Playground>
WEBFLOW_COLLECTION_ID=<id de la Collection "Audits">
WEBFLOW_SITE_DOMAIN=https://tu-sitio.webflow.io
```

Requiere **Node >= 22.3** en la imagen: descomentá el bloque marcado en el
[`Dockerfile`](Dockerfile).

Dos cosas que descubrimos leyendo la doc de Webflow y que definen este diseño:

- **El server remoto (`https://mcp.webflow.com/mcp`) no sirve.** Autentica solo
  por OAuth con consentimiento en navegador; no hay credencial
  machine-to-machine documentada, asi que un worker headless no puede entrar.
  Por eso usamos el server **local por stdio** (`npx webflow-mcp-server`), que
  toma un token estatico por `WEBFLOW_TOKEN`.
- **Publicar son dos pasos.** El MCP server expone una sola tool
  `data_cms_tool` con un parametro `action`. Los items se crean **siempre como
  draft**, asi que el flujo es `create_collection_items` -> capturar el item id
  -> `publish_collection_items`. No existe create-as-live por MCP (el REST si lo
  tiene, de ahi que `rest` sea un call y `mcp` dos).

### Schema de la Collection "Audits" en Webflow

Los slugs de los campos tienen que coincidir exactamente con
`build_field_data()` en [`app/publisher/__init__.py`](app/publisher/__init__.py):

| Campo | Tipo en Webflow | Slug |
|---|---|---|
| Name | Plain text | `name` |
| Slug | Slug | `slug` |
| Contract address | Plain text | `contract-address` |
| Network | Plain text | `network` |
| Verdict | Plain text | `verdict` |
| Total findings | Number | `total-findings` |
| Analyzed at | Plain text | `analyzed-at` |
| Report | **Rich text** | `report` |
| Summary | Plain text (long) | `summary` |

`report` tiene que ser Rich Text: ahi entra el HTML del reporte. Es inline-styled
y sin `<script>` a proposito, porque Webflow sanitiza esos campos.

Publicar es **best-effort**: si Webflow falla, el audit queda `done` igual y el
share link cae al de este backend. Un problema de CMS no invalida un analisis.

---

## Deploy en DigitalOcean

Droplet chico (2 vCPU / 2GB) con Docker:

```bash
git clone -b back <tu-repo> smartcheck && cd smartcheck
cp .env.example .env && nano .env      # poné PUBLIC_BASE_URL y CORS_ORIGINS
docker compose up -d --build
```

Antes de la demo, dos cosas que importan:

1. **`CORS_ORIGINS`** tiene que tener el dominio de Webflow, no `*`.
2. **HTTPS.** El sitio de Webflow es HTTPS, asi que un backend en HTTP puro va a
   ser bloqueado por mixed content. Poné Caddy adelante (2 lineas de Caddyfile y
   te resuelve el cert solo) o el load balancer de DO.

---

## Pendientes conscientes del MVP

- **Imports de OpenZeppelin en codigo pegado fallan.** Sin `node_modules` ni
  remappings, Slither no resuelve `@openzeppelin/...`. Por address verificada si
  funciona, porque Sourcify devuelve el arbol completo. El fix es aplanar
  (flatten) o montar las libs en la imagen.
- **PDF.** Por ahora hay Markdown y HTML. El HTML ya imprime bien a PDF desde el
  browser; si hace falta un PDF server-side, `weasyprint` es el camino corto.
- **Rate limiting.** No hay. Cualquiera puede encolar audits.
- **UC6-UC9** (comparar versiones, historial por wallet, CI/CLI) no estan.
  El `GET /api/audits/{id}/raw` ya guarda el JSON crudo pensando en UC6.
- **Resumen ejecutivo con LLM.** `report.build_plain_summary()` es determinista.
  Si despues querés prosa generada, ese es el punto de enganche y este sigue
  siendo el fallback cuando la API falle.
