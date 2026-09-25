# Auditor OWASP Smart Contract Top 10 — Spec técnica

Checklist interactivo que analiza un contrato deployado en testnet (o código pegado) y mapea los hallazgos contra las 10 categorías del **OWASP Smart Contract Security Top 10**, con reportes exportables y en lenguaje claro (no otro "risk score" genérico).

---

## 1. Objetivo y diferencial

- Ningún auditor automático existente (ContractLens, Shieldon, escáneres tipo Apify, etc.) usa el **OWASP SCS Top 10** como taxonomía de salida — todos inventan sus propias categorías.
- Foco **educativo + testnet**: pensado para el flujo "estoy por pasar a mainnet, decime en criollo qué me falta", no para trading bots ni agentes DeFi.
- Doble uso: herramienta de hackathon y herramienta interna para auditar los contratos propios de tokenización inmobiliaria antes de escalarlos.

---

## 2. Actores

- **Desarrollador Web3**: pega address o código, corre el análisis, lee el checklist, exporta o comparte.
- **Estudiante / curioso**: explora la taxonomía sin necesariamente auditar nada (modo educativo).
- Sin roles de admin, sin login tradicional para el MVP.

---

## 3. Flujo principal (happy path)

1. Landing con input de dirección + selector de red testnet (arranca con Sepolia).
2. Usuario pega dirección y confirma.
3. Backend busca el código fuente verificado (Sourcify primero, fallback a Etherscan API v2 en modo Sepolia).
4. Si no está verificado → cae al flujo alternativo de pegar código fuente (UC2).
5. Se dispara un job de análisis con Slither.
6. Se mapean los hallazgos de Slither a las 10 categorías OWASP SCS.
7. Se muestra el checklist: cada categoría en estado `OK / Advertencia / Riesgo / No aplica`, con explicación en criollo.
8. Usuario hace clic en un ítem con problema → ve detalle (línea de código, por qué es riesgoso, sugerencia de fix).
9. Exporta (PDF/Markdown) o comparte por link.

---

## 4. Casos de uso

### MVP (hackathon)

| # | Caso de uso | Notas |
|---|---|---|
| UC1 | Auditar por dirección verificada | Flujo principal |
| UC2 | Auditar pegando código fuente | Textarea con `.sol`, para no verificados o locales |
| UC3 | Explorar taxonomía sin auditar | Cada categoría es clickeable en modo "solo aprender" |
| UC4 | Exportar reporte PDF/Markdown | Para pitch del hackathon y documentación |
| UC5 | Compartir vía link | Hash público, sin necesidad de cuenta |

### Extensiones (post-hackathon)

| # | Caso de uso | Notas |
|---|---|---|
| UC6 | Comparar dos versiones de un contrato | Ver qué ítems pasaron de rojo a verde tras un fix |
| UC7 | Historial de auditorías propias | Conectar wallet solo para firmar/identificar, sin login clásico |
| UC8 | Integración CI/CLI | Endpoint o paquete para correr en GitHub Actions |
| UC9 | Multi-red | Sumar Base Sepolia, Polygon Amoy, etc. |

### Casos borde

- Dirección que es una EOA, no un contrato → mensaje claro, no error genérico.
- Contrato con dependencias externas (OpenZeppelin, etc.) → decidir si se analizan también o solo el contrato principal.
- Timeout de Slither en contratos grandes → mostrar progreso/resultado parcial, no colgar la UI.
- Rate limit de la API del explorer → cachear resultado por address para no re-pedir el source ya auditado.
- Código pegado por el usuario → sandboxear la ejecución (nunca correr Slither sobre input arbitrario sin aislamiento y timeout).

---

## 5. Arquitectura técnica

### 5.1 Stack

- **Backend**: Laravel (API REST, sin Blade — el frontend es una SPA separada).
- **Frontend**: SPA liviana (Vite + Alpine.js o React, lo que te sea más cómodo desplegar rápido) consumiendo la API.
- **Análisis estático**: Slither (Python) corriendo en un contenedor aparte o vía `Process` de Laravel con Python instalado en el mismo host.
- **Compilación de contratos**: `solc` (o Foundry si ya lo tenés instalado) para poder correr Slither sobre código pegado.
- **Colas**: Laravel Queue (`database` o `redis` driver alcanza para el hackathon) — el análisis de Slither no debe ser síncrono.
- **Base de datos**: SQLite o MySQL, una sola tabla principal (`audits`) alcanza para el MVP.
- **Fuente de código verificado**: API de **Sourcify** (gratis, sin API key, multichain) como primera opción; **Etherscan API v2** (unificada, requiere API key) como fallback.
- **Export**: `barryvdh/laravel-dompdf` o `spatie/laravel-pdf` para PDF; Markdown se genera directo desde la misma estructura de datos.

### 5.2 Por qué esta división

- Slither es Python puro — no tiene sentido reimplementar detectores en PHP. Laravel orquesta, Python analiza.
- El análisis puede tardar (compilación + detectores) → por eso va a cola, no en el request HTTP. El frontend hace polling sobre el estado.
- Separar el mapeo OWASP como config propia (no está en ningún lado hecho) es el corazón del diferencial — vive en Laravel, no en Slither.

### 5.3 Modelo de datos

```
audits
- id (uuid)
- network            (string, ej "sepolia")
- address            (string, nullable — null si vino por código pegado)
- source_type        (enum: verified | pasted)
- source_code        (longtext, guardado para poder re-auditar / comparar)
- status             (enum: pending | processing | done | error)
- raw_slither_output (json, nullable)
- checklist          (json, nullable) -- resultado ya mapeado a las 10 categorías
- share_hash         (string, unique, indexado)
- error_message      (text, nullable)
- created_at / updated_at
```

Estructura sugerida para `checklist` (json):

```json
{
  "SC01": { "name": "Access Control", "status": "risk", "findings": [ { "detector": "unprotected-upgrade", "line": 42, "severity": "high", "explanation": "...", "suggestion": "..." } ] },
  "SC02": { "name": "Reentrancy", "status": "ok", "findings": [] },
  "...": "..."
}
```

### 5.4 Mapeo Slither → OWASP SCS Top 10

Esto es un archivo de config propio (`config/owasp_scs_mapping.php` o JSON), **no existe publicado en ningún lado** así que lo armás vos mismo a partir de los ~90 detectores de Slither y las 10 categorías OWASP. Ejemplo de forma:

```php
return [
    'unprotected-upgrade'   => 'SC01', // Access Control
    'reentrancy-eth'        => 'SC02', // Reentrancy
    'reentrancy-no-eth'     => 'SC02',
    'arbitrary-send-eth'    => 'SC01',
    'unchecked-transfer'    => 'SC05', // Unchecked External Calls (ajustar según versión final del Top 10)
    'timestamp'             => 'SC07', // Manipulación de oráculos / timestamp
    // ... completar contra el listado completo de detectores de Slither
];
```

Regla de agregación por categoría:
- Sin findings → `ok`
- Al menos un finding `low`/`medium` → `warning`
- Al menos un finding `high` → `risk`
- Categoría sin detectores mapeados que apliquen → `n/a`

### 5.5 Endpoints API

```
POST   /api/audits                 { address, network }        -> crea audit (source_type=verified), dispara job
POST   /api/audits/source          { source_code, network }     -> crea audit (source_type=pasted), dispara job
GET    /api/audits/{id}                                         -> status + checklist si ya está listo
GET    /api/audits/{id}/export?format=pdf|md                    -> descarga reporte
GET    /api/audits/share/{hash}                                 -> vista pública read-only
```

### 5.6 Job de análisis (pseudocódigo)

```
RunAuditJob(audit):
  1. si source_type == verified:
       code = SourcifyClient.fetch(address, network)
         fallback: EtherscanClient.fetch(address, network)
     si no hay code -> status=error, return
  2. guardar code en audit.source_code
  3. compilar con solc (detectar versión de pragma automáticamente o pedir fallback a la más reciente)
  4. correr slither --json sobre el artefacto compilado, con timeout (ej. 60s)
  5. parsear resultado, mapear cada detector a categoría OWASP vía el config
  6. agregar findings por categoría -> armar checklist json
  7. guardar checklist, status=done
  8. catch cualquier excepción -> status=error, error_message
```

### 5.7 Frontend (flujo de pantallas)

1. **Home**: input address + selector red, o toggle a "pegar código".
2. **Cargando**: polling a `GET /api/audits/{id}` cada 2-3s mientras `status=processing`.
3. **Resultado**: grid/lista de 10 categorías con badge de color, click expande detalle.
4. **Modo explorar**: mismo componente de checklist pero sin datos de audit real, solo la explicación educativa de cada categoría (se puede servir como JSON estático, sin pegar a la API).
5. Botones de exportar / compartir en la vista de resultado.

### 5.8 Infraestructura / deploy

- Contenedor único para el hackathon: PHP + Composer (Laravel) + Python + pip (Slither) + solc, todo en la misma imagen para simplificar el deploy rápido. Separar en microservicio Python solo si el análisis se vuelve cuello de botella.
- Variables de entorno: `ETHERSCAN_API_KEY` (opcional, solo fallback), `SLITHER_TIMEOUT`, `QUEUE_CONNECTION`.
- Sandboxing del código pegado por el usuario: correr Slither con usuario sin privilegios, timeout duro, y sin acceso de red desde ese proceso.

---

## 6. Orden sugerido de implementación

1. Modelo `Audit` + migración + endpoints CRUD básicos (sin Slither todavía, devolver mock).
2. Cliente Sourcify/Etherscan para traer código verificado.
3. Job que corre Slither sobre un contrato fijo de prueba y devuelve el JSON crudo.
4. Armar el archivo de mapeo Slither → OWASP SCS (el trabajo de investigación más largo).
5. Lógica de agregación → checklist final.
6. Frontend: pantalla de input + polling + resultado.
7. Export PDF/Markdown.
8. Compartir por hash.
9. (Extensión) UC6-UC9 si sobra tiempo.

---

## 7. Preguntas abiertas para definir antes de codear

- ¿Servís el mapeo OWASP como PHP config o como tabla en DB (más fácil de ajustar sin deploy)?
- ¿Corrés Slither en el mismo contenedor que Laravel o como microservicio aparte desde el arranque? (para el hackathon, mismo contenedor es más rápido de armar)
- ¿Qué versión exacta del OWASP Smart Contract Top 10 vas a fijar como referencia, para no perseguir cambios del estándar en medio del desarrollo?
