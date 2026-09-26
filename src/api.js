/**
 * Cliente de la API de SmartCheck.
 *
 * La URL del backend NO esta hardcodeada: viene de window.SMARTCHECK_API, que
 * se setea en el snippet del <head> de Webflow. Asi el mismo archivo servido
 * por CDN sirve para local, staging y produccion.
 */

// Backend desplegado. Es el default a proposito: si alguien pega el embed sin el
// snippet del <head>, la app funciona igual. Un default a localhost romperia en
// Webflow por mixed content y el error no diria nada util.
const DEFAULT_API = "https://138.197.155.202.sslip.io";

export function apiBase() {
  const configured = (window.SMARTCHECK_API || "").trim();
  return (configured || DEFAULT_API).replace(/\/+$/, "");
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${apiBase()}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (cause) {
    // fetch solo rechaza por red/CORS, nunca por status HTTP.
    // El detalle tecnico (URL, causa) va a la consola, no al mensaje que ve el
    // usuario: la URL del servidor y los nombres de variables de entorno no le
    // sirven a nadie que no sea quien lo deployo.
    console.error(`[smartcheck] no se pudo contactar ${apiBase()}${path}`, cause);
    throw new ApiError(
      "No se pudo conectar con el servicio de análisis. " +
        "Puede estar momentáneamente fuera de servicio; probá de nuevo en un rato.",
      0,
    );
  }

  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    // respuesta no-JSON (un 502 de nginx, por ejemplo)
  }

  if (!response.ok) {
    throw new ApiError(extractError(payload) || `Error ${response.status}`, response.status);
  }
  return payload;
}

/** FastAPI devuelve los errores de validacion de pydantic como un array en `detail`. */
function extractError(payload) {
  if (!payload) return null;
  const { detail } = payload;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg?.replace(/^Value error,\s*/, "") || String(d)).join(" ");
  }
  return null;
}

export const api = {
  health: () => request("/health"),
  networks: () => request("/api/networks"),
  taxonomy: () => request("/api/taxonomy"),

  auditAddress: (address, network) =>
    request("/api/audits", {
      method: "POST",
      body: JSON.stringify({ address, network }),
    }),

  auditSource: (sourceCode, network) =>
    request("/api/audits/source", {
      method: "POST",
      body: JSON.stringify({ source_code: sourceCode, network }),
    }),

  getAudit: (id) => request(`/api/audits/${encodeURIComponent(id)}`),

  exportUrl: (id, format) =>
    `${apiBase()}/api/audits/${encodeURIComponent(id)}/export?format=${format}`,
};

/**
 * Hace polling hasta que el audit termina.
 * Devuelve una funcion de cancelacion para no dejar timers colgados si el
 * usuario arranca otro audit antes de que el anterior cierre.
 */
/** Un fallo que probablemente se resuelva solo si reintentamos. */
function isTransient(error) {
  // 0 = red/CORS, 429 = rate limit, 5xx = el backend se esta recuperando
  return error.status === 0 || error.status === 429 || error.status >= 500;
}

export function pollAudit(
  id,
  { onUpdate, onDone, onError, intervalMs = 2500, maxMs = 300000, maxFailures = 5 },
) {
  const startedAt = Date.now();
  let cancelled = false;
  let timer = null;
  let failures = 0;

  async function tick() {
    if (cancelled) return;
    try {
      const audit = await api.getAudit(id);
      if (cancelled) return;
      failures = 0;

      onUpdate?.(audit);

      if (audit.status === "done") return onDone?.(audit);
      if (audit.status === "error") {
        return onError?.(new ApiError(audit.error_message || "El analisis fallo", 0));
      }
      if (Date.now() - startedAt > maxMs) {
        return onError?.(
          new ApiError(
            "El analisis esta tardando mas de lo esperado. Probá recargando en un rato.",
            0,
          ),
        );
      }
      timer = setTimeout(tick, intervalMs);
    } catch (error) {
      if (cancelled) return;

      // El analisis ya esta corriendo en el backend: un 429 o un corte de red
      // momentaneo no es razon para tirar la vista. Reintentamos con backoff y
      // solo nos rendimos si falla varias veces seguidas.
      failures += 1;
      if (isTransient(error) && failures < maxFailures) {
        const backoff = Math.min(intervalMs * 2 ** failures, 20000);
        timer = setTimeout(tick, backoff);
        return;
      }
      onError?.(error);
    }
  }

  tick();
  return () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
  };
}

export { ApiError };
