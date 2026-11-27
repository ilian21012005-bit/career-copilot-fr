/** Safe DOM construction helpers (textContent + addEventListener), badges, toasts, drawer. */

const STATUS_META = {
  new: ["Nouvelle", "accent"],
  shortlist: ["Shortlist", "accent"],
  prepared: ["Préparée", "warning"],
  to_finish: ["À finaliser", "warning"],
  applied: ["Envoyée", "success"],
  sent: ["Envoyée", "success"],
  replied: ["Réponse", "success"],
  interview: ["Entretien", "success"],
  submission_pending: ["Envoi en cours", "warning"],
  submission_unknown: ["À vérifier", "danger"],
  ignored: ["Ignorée", "neutral"],
  running: ["En cours", "accent"],
  success: ["Succès", "success"],
  failed: ["Échec", "danger"],
  fresh: ["À jour", "success"],
  stale: ["Obsolète", "warning"],
  unknown: ["Inconnu", "neutral"],
  info: ["Info", "neutral"],
  warning: ["Attention", "warning"],
  critical: ["Critique", "danger"],
  ok: ["OK", "success"],
  degraded: ["Dégradé", "warning"],
  error: ["Erreur", "danger"],
};

export function safeHttpUrl(raw) {
  if (!raw || typeof raw !== "string") return null;
  try {
    const parsed = new URL(raw.trim(), window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function el(tag, attrs = null, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, val] of Object.entries(attrs)) {
      if (val === null || val === undefined || val === false) continue;
      if (key === "className") {
        node.className = String(val);
      } else if (key === "text") {
        node.textContent = String(val);
      } else if (key === "dataset" && typeof val === "object") {
        for (const [dk, dv] of Object.entries(val)) {
          if (dv !== undefined && dv !== null) node.dataset[dk] = String(dv);
        }
      } else if (key === "on" && typeof val === "object") {
        for (const [ev, handler] of Object.entries(val)) {
          if (typeof handler === "function") node.addEventListener(ev, handler);
        }
      } else if (key === "value" || key === "checked" || key === "disabled" || key === "selected") {
        node[key] = val;
      } else if (val === true) {
        node.setAttribute(key, "");
      } else {
        node.setAttribute(key, String(val));
      }
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function externalLink(rawUrl, label, className = "") {
  const safe = safeHttpUrl(rawUrl);
  if (!safe) return null;
  return el("a", {
    href: safe,
    target: "_blank",
    rel: "noopener noreferrer",
    className,
    text: label,
  });
}

export function badge(text, tone = "neutral") {
  return el("span", { className: `badge badge-${tone}`, text });
}

export function statusBadge(value) {
  const key = String(value || "unknown").toLowerCase();
  const [label, tone] = STATUS_META[key] || [String(value || "—"), "neutral"];
  return badge(label, tone);
}

export function formatDate(iso) {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return String(iso).slice(0, 16);
  return parsed.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function stateBox(kind, message, actionNode = null) {
  const cls = kind === "error" ? "state-box is-error" : "state-box";
  return el("div", { className: cls }, el("p", { text: message }), actionNode);
}

export function showToast(message, tone = "success") {
  const region = document.getElementById("toast-region");
  if (!region) return;
  const item = el("div", { className: `toast toast-${tone}`, text: message });
  region.appendChild(item);
  window.setTimeout(() => item.remove(), 4200);
}

export function createDrawerController() {
  const backdrop = document.getElementById("detail-drawer");
  const titleEl = document.getElementById("drawer-title");
  const bodyEl = document.getElementById("drawer-body");
  const closeBtn = document.getElementById("drawer-close");

  const close = () => {
    if (!backdrop) return;
    backdrop.hidden = true;
    if (bodyEl) bodyEl.replaceChildren();
  };
  const open = (title, contentNode) => {
    if (!backdrop || !titleEl || !bodyEl) return;
    titleEl.textContent = title;
    bodyEl.replaceChildren(contentNode);
    backdrop.hidden = false;
    closeBtn?.focus();
  };

  closeBtn?.addEventListener("click", close);
  backdrop?.addEventListener("click", (ev) => {
    if (ev.target === backdrop) close();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && backdrop && !backdrop.hidden) close();
  });
  return { open, close };
}
