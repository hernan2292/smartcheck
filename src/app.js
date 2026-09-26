/**
 * SmartCheck — frontend.
 *
 * Vanilla JS, sin build step. Esto no es un capricho: a Webflow no le podes
 * subir un bundle de Vite, solo pegar codigo o cargar un <script src>. Sin
 * bundler, el mismo archivo funciona en local y servido por CDN.
 *
 * Monta en #smartcheck-app. Config via window.SMARTCHECK_API.
 */

import { api, pollAudit, apiBase } from "./api.js";
import { CATEGORIES, OWASP_SCS_VERSION } from "./taxonomy.js";

const STATUS_LABEL = { ok: "OK", warning: "Advertencia", risk: "Riesgo", "n/a": "No aplica" };
const SEVERITY_LABEL = { high: "Alta", medium: "Media", low: "Baja", info: "Info" };
const VERDICT_LABEL = { listo: "Listo", revisar: "Revisar", "no-listo": "No listo" };

let cancelPolling = null;
let root = null;

// --- Helpers de DOM ---------------------------------------------------------

/** Crea un elemento. Usa textContent, nunca innerHTML: el texto viene de la API. */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "hidden") node.hidden = Boolean(value);
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child) node.append(child);
  }
  return node;
}

function $(selector) {
  return root.querySelector(selector);
}

function clear(node) {
  while (node.firstChild) node.firstChild.remove();
}

// --- Render: formulario ----------------------------------------------------

function renderForm(networks) {
  // Los dos selects se construyen desde cero en vez de clonar: un <option> no
  // se puede compartir entre dos <select>, y clonar seria mas codigo que esto.
  const netSelect = (id) =>
    el("div", { class: "sc-field" }, [
      el("label", { class: "sc-label", for: id, text: "Red" }),
      el(
        "select",
        { class: "sc-select", id },
        networks.map((n) =>
          el("option", { value: n.slug, text: n.label, selected: n.slug === "sepolia" }),
        ),
      ),
    ]);

  return el("div", {}, [
    el("div", { class: "sc-tabs", role: "tablist" }, [
      el("button", {
        class: "sc-tab",
        role: "tab",
        id: "sc-tab-address",
        "aria-selected": "true",
        "aria-controls": "sc-panel-address",
        text: "Por dirección",
        onclick: () => switchTab("address"),
      }),
      el("button", {
        class: "sc-tab",
        role: "tab",
        id: "sc-tab-source",
        "aria-selected": "false",
        "aria-controls": "sc-panel-source",
        text: "Pegar código",
        onclick: () => switchTab("source"),
      }),
      el("button", {
        class: "sc-tab",
        role: "tab",
        id: "sc-tab-explore",
        "aria-selected": "false",
        "aria-controls": "sc-panel-explore",
        text: "Explorar taxonomía",
        onclick: () => switchTab("explore"),
      }),
    ]),

    // UC1 — auditar por address verificada
    el(
      "form",
      {
        class: "sc-panel",
        id: "sc-panel-address",
        role: "tabpanel",
        "aria-labelledby": "sc-tab-address",
        onsubmit: submitAddress,
      },
      [
        el("div", { class: "sc-row" }, [
          el("div", { class: "sc-field" }, [
            el("label", { class: "sc-label", for: "sc-address", text: "Dirección del contrato" }),
            el("input", {
              class: "sc-input",
              id: "sc-address",
              type: "text",
              placeholder: "0x...",
              autocomplete: "off",
              spellcheck: "false",
              required: "required",
            }),
          ]),
          netSelect("sc-network-address"),
          el("button", { class: "sc-btn", type: "submit", text: "Auditar" }),
        ]),
        el("p", {
          class: "sc-hint",
          text:
            "Busca el código verificado en Sourcify y, si no está, en Etherscan. " +
            "Si no aparece en ninguno, pegá el código en la otra pestaña.",
        }),
      ],
    ),

    // UC2 — auditar codigo pegado
    el(
      "form",
      {
        class: "sc-panel",
        id: "sc-panel-source",
        role: "tabpanel",
        "aria-labelledby": "sc-tab-source",
        hidden: true,
        onsubmit: submitSource,
      },
      [
        el("div", { class: "sc-field" }, [
          el("label", { class: "sc-label", for: "sc-source", text: "Código Solidity" }),
          el("textarea", {
            class: "sc-textarea",
            id: "sc-source",
            placeholder: "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n\ncontract MiContrato {\n    ...\n}",
            spellcheck: "false",
            required: "required",
          }),
        ]),
        el("div", { class: "sc-row" }, [
          netSelect("sc-network-source"),
          el("button", { class: "sc-btn", type: "submit", text: "Auditar" }),
        ]),
        el("p", {
          class: "sc-hint",
          text:
            "Si el contrato importa OpenZeppelin, pegalo aplanado (flattened): " +
            "sin las dependencias el compilador no puede resolver los imports.",
        }),
      ],
    ),

    // UC3 — explorar sin auditar
    el("div", {
      class: "sc-panel",
      id: "sc-panel-explore",
      role: "tabpanel",
      "aria-labelledby": "sc-tab-explore",
      hidden: true,
    }),

    el("div", { id: "sc-output", "aria-live": "polite" }),
  ]);
}

function switchTab(name) {
  for (const tab of ["address", "source", "explore"]) {
    const isActive = tab === name;
    $(`#sc-tab-${tab}`).setAttribute("aria-selected", String(isActive));
    $(`#sc-panel-${tab}`).hidden = !isActive;
  }
  if (name === "explore") renderExplore();
}

// --- Render: modo explorar (sin API) ---------------------------------------

function renderExplore() {
  const panel = $("#sc-panel-explore");
  if (panel.dataset.rendered) return;
  panel.dataset.rendered = "1";

  panel.append(
    el("p", {
      class: "sc-hint",
      text: `Las 10 categorías del OWASP Smart Contract Security Top 10 (${OWASP_SCS_VERSION}). Clickeá cualquiera para ver el detalle.`,
    }),
    el(
      "div",
      { class: "sc-cats" },
      CATEGORIES.map((cat) =>
        renderCategory({
          ...cat,
          status: "n/a",
          findings: [],
          finding_count: 0,
          note: cat.static_analysis_blind
            ? "El análisis estático no puede detectar esto: requiere simular composabilidad económica."
            : null,
        }, { exploreMode: true }),
      ),
    ),
  );
}

// --- Render: una categoria -------------------------------------------------

function renderCategory(entry, { exploreMode = false } = {}) {
  const bodyId = `sc-body-${entry.id}${exploreMode ? "-explore" : ""}`;
  const count = entry.finding_count ?? entry.findings?.length ?? 0;

  const body = el("div", { class: "sc-cat-body", id: bodyId, hidden: true }, [
    el("h4", { text: "Qué es" }),
    el("p", { text: entry.plain }),
    entry.note ? el("p", { class: "sc-note", text: entry.note }) : null,
    ...(exploreMode ? [] : [renderFindingsSection(entry, count)]),
    el("h4", { text: "Cómo se arregla" }),
    el("p", { text: entry.fix }),
  ]);

  const header = el(
    "button",
    {
      class: "sc-cat-header",
      type: "button",
      "aria-expanded": "false",
      "aria-controls": bodyId,
      onclick: (event) => {
        const button = event.currentTarget;
        const open = button.getAttribute("aria-expanded") === "true";
        button.setAttribute("aria-expanded", String(!open));
        body.hidden = open;
      },
    },
    [
      el("span", { class: "sc-cat-id", text: entry.id }),
      el("span", { class: "sc-cat-name", text: entry.name }),
      exploreMode
        ? null
        : el("span", {
            class: "sc-badge",
            text: count ? `${STATUS_LABEL[entry.status]} · ${count}` : STATUS_LABEL[entry.status],
          }),
      el("span", { class: "sc-chevron", "aria-hidden": "true", text: "›" }),
    ],
  );

  return el("div", { class: "sc-cat", "data-status": entry.status }, [header, body]);
}

function renderFindingsSection(entry, count) {
  if (!count) {
    return el("div", {}, [
      el("h4", { text: "Hallazgos" }),
      el("p", {
        class: "sc-empty",
        text:
          entry.status === "n/a"
            ? "Fuera del alcance del análisis estático."
            : "Sin hallazgos en esta categoría.",
      }),
    ]);
  }

  return el("div", {}, [
    el("h4", { text: `Hallazgos (${count})` }),
    el(
      "ul",
      { class: "sc-findings" },
      entry.findings.map((f) =>
        el("li", { class: "sc-finding" }, [
          el("div", { class: "sc-finding-head" }, [
            el("code", { text: f.detector }),
            el("span", {
              class: "sc-sev",
              "data-sev": f.severity,
              text: SEVERITY_LABEL[f.severity] || f.severity,
            }),
            f.line
              ? el("span", {
                  class: "sc-finding-loc",
                  text: `${f.file || "contrato"} · línea ${f.line}`,
                })
              : null,
          ]),
          f.explanation ? el("pre", { class: "sc-finding-desc", text: f.explanation }) : null,
        ]),
      ),
    ),
  ]);
}

// --- Render: resultado -----------------------------------------------------

function renderResult(audit) {
  const output = $("#sc-output");
  clear(output);

  const checklist = audit.checklist || {};
  const totals = checklist.totals || {};
  const categories = Object.values(checklist.categories || {});
  const verdict = totals.verdict || "revisar";

  const subject = audit.address || audit.contract_name || "código pegado";
  const shareUrl = audit.public_url || audit.share_url;

  output.append(
    el("div", { class: "sc-verdict", "data-verdict": verdict }, [
      el("strong", { class: "sc-verdict-label", text: VERDICT_LABEL[verdict] || verdict }),
      el("span", { text: audit.summary || "" }),
    ]),

    el("div", { class: "sc-meta" }, [
      el("span", {}, [document.createTextNode("Contrato: "), el("code", { text: subject })]),
      el("span", { text: `Red: ${audit.network}` }),
      el("span", { text: `Hallazgos: ${totals.total_findings ?? 0}` }),
      el("span", { text: `OWASP SCS ${checklist.owasp_version || OWASP_SCS_VERSION}` }),
    ]),

    el("div", { class: "sc-actions" }, [
      el("a", {
        class: "sc-btn sc-btn--ghost",
        href: api.exportUrl(audit.id, "md"),
        text: "Descargar Markdown",
      }),
      el("a", {
        class: "sc-btn sc-btn--ghost",
        href: api.exportUrl(audit.id, "html"),
        target: "_blank",
        rel: "noopener",
        text: "Ver reporte completo",
      }),
      shareUrl
        ? el("button", {
            class: "sc-btn sc-btn--ghost",
            type: "button",
            text: "Copiar link",
            onclick: (event) => copyLink(event.currentTarget, shareUrl),
          })
        : null,
    ]),

    el(
      "div",
      { class: "sc-cats" },
      categories.map((entry) => renderCategory(entry)),
    ),
  );

  output.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function copyLink(button, url) {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(url);
    button.textContent = "¡Copiado!";
  } catch {
    // clipboard falla sin HTTPS o sin permiso: mostrar el link es mejor que nada
    window.prompt("Copiá el link:", url);
    return;
  }
  setTimeout(() => {
    button.textContent = original;
  }, 1800);
}

// --- Estados intermedios ---------------------------------------------------

function showLoading(message) {
  const output = $("#sc-output");
  clear(output);
  output.append(
    el("div", { class: "sc-loading" }, [
      el("div", { class: "sc-spinner", "aria-hidden": "true" }),
      el("span", { text: message }),
    ]),
  );
}

function showError(message) {
  const output = $("#sc-output");
  clear(output);

  // El backend manda errores de compilacion de solc en varias lineas, con un
  // caret que apunta a la columna exacta. Un <p> colapsa los espacios y arruina
  // esa alineacion, asi que el detalle va en un <pre>.
  const [resumen, ...resto] = String(message).split(/\n\s*\n/);
  const detalle = resto.join("\n\n").trim();

  output.append(
    el("div", { class: "sc-alert", role: "alert" }, [
      el("strong", { text: "No se pudo completar el análisis" }),
      el("p", { style: "margin:6px 0 0", text: resumen.trim() }),
      detalle ? el("pre", { class: "sc-error-detail", text: detalle }) : null,
    ]),
  );
}

function setBusy(busy) {
  for (const button of root.querySelectorAll('.sc-panel button[type="submit"]')) {
    button.disabled = busy;
    button.textContent = busy ? "Analizando..." : "Auditar";
  }
}

// --- Submit ----------------------------------------------------------------

async function submitAddress(event) {
  event.preventDefault();
  const address = $("#sc-address").value.trim();
  const network = $("#sc-network-address").value;
  await runAudit(
    () => api.auditAddress(address, network),
    "Buscando el código verificado y corriendo Slither...",
  );
}

async function submitSource(event) {
  event.preventDefault();
  const sourceCode = $("#sc-source").value;
  const network = $("#sc-network-source").value;
  await runAudit(() => api.auditSource(sourceCode, network), "Compilando y corriendo Slither...");
}

async function runAudit(start, loadingMessage) {
  // Si habia un audit en curso, cortar su polling para que no pise este
  cancelPolling?.();
  cancelPolling = null;

  setBusy(true);
  showLoading(loadingMessage);

  try {
    const audit = await start();

    if (audit.status === "done") {
      setBusy(false);
      return renderResult(audit);
    }
    if (audit.status === "error") {
      setBusy(false);
      return showError(audit.error_message || "El análisis falló");
    }

    cancelPolling = pollAudit(audit.id, {
      onDone: (final) => {
        setBusy(false);
        cancelPolling = null;
        renderResult(final);
      },
      onError: (error) => {
        setBusy(false);
        cancelPolling = null;
        showError(error.message);
      },
    });
  } catch (error) {
    setBusy(false);
    showError(error.message);
  }
}

// --- Bootstrap -------------------------------------------------------------

const FALLBACK_NETWORKS = [
  { slug: "sepolia", label: "Sepolia" },
  { slug: "base-sepolia", label: "Base Sepolia" },
  { slug: "polygon-amoy", label: "Polygon Amoy" },
  { slug: "arbitrum-sepolia", label: "Arbitrum Sepolia" },
  { slug: "optimism-sepolia", label: "Optimism Sepolia" },
];

export async function mount(selector = "#smartcheck-app") {
  const container = document.querySelector(selector);
  if (!container) {
    console.warn(`[smartcheck] No existe ${selector} en la página.`);
    return;
  }

  root = container;
  root.classList.add("sc-app");

  // La lista de redes la manda el backend, pero el form tiene que dibujarse
  // igual si el backend esta caido: asi el modo explorar sigue sirviendo.
  let networks = FALLBACK_NETWORKS;
  let backendDown = false;
  try {
    const payload = await api.networks();
    networks = payload.networks;
  } catch {
    backendDown = true;
  }

  // Se limpia recien aca, no antes del fetch: asi el placeholder de "cargando"
  // que trae el embed sigue visible hasta que hay algo con que reemplazarlo.
  clear(root);
  root.append(renderForm(networks));

  if (backendDown) {
    $("#sc-output").append(
      el("div", { class: "sc-alert sc-alert--info" }, [
        el("strong", { text: "El backend no responde" }),
        el("p", {
          style: "margin:6px 0 0",
          text: `No se pudo contactar ${apiBase()}. Podés explorar la taxonomía igual, pero no auditar todavía.`,
        }),
      ]),
    );
  }
}

// Sin auto-mount a proposito: tanto el embed de Webflow como index.html llaman
// a mount() explicitamente. Montar solo tambien haria doble fetch de /networks.
