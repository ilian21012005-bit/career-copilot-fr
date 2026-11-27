/** Main Career Copilot standalone UI orchestrator (tabs, auth token, theme, state). */

import { ApiError, careerApi, getStoredToken, setStoredToken } from "./api.js";
import { createDrawerController, el, showToast, stateBox } from "./dom.js";
import { renderOffersView } from "./views_offers.js";
import {
  renderApplicationsView,
  renderKitsView,
  renderOverviewView,
  renderRunsView,
  renderSetupView,
} from "./views_ops.js";

const THEME_STORAGE_KEY = "career_copilot_theme";

const VIEW_RENDERERS = {
  overview: renderOverviewView,
  offers: renderOffersView,
  applications: renderApplicationsView,
  kits: renderKitsView,
  runs: renderRunsView,
  setup: renderSetupView,
};

const state = {
  activeView: "overview",
  token: getStoredToken(),
  offerFilters: { track: "", status: "", q: "", min_score: "", eligible: false },
  appSinceDays: 30,
  kitsReadyOnly: false,
};

let drawer = null;

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const btn = document.getElementById("btn-theme-toggle");
  if (btn) {
    btn.textContent = dark ? "Thème clair" : "Thème sombre";
    btn.setAttribute("aria-pressed", String(dark));
  }
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, dark ? "dark" : "light");
  } catch {
    // Ignore storage unavailability.
  }
}

function initTheme() {
  let saved = "";
  try {
    saved = window.localStorage.getItem(THEME_STORAGE_KEY) || "";
  } catch {
    saved = "";
  }
  if (!saved && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    saved = "dark";
  }
  applyTheme(saved === "dark" ? "dark" : "light");
}

function setAuthBarOpen(open, hintText = "") {
  const bar = document.getElementById("auth-bar");
  const toggleBtn = document.getElementById("btn-token-toggle");
  const hint = document.getElementById("auth-hint");
  if (bar) bar.hidden = !open;
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", String(open));
  if (hint && hintText) hint.textContent = hintText;
  if (open) document.getElementById("token-input")?.focus();
}

function updateText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = String(value);
}

function updateHealthPill(health) {
  const pill = document.getElementById("health-pill");
  if (!pill) return;
  const walStatus = health?.checks?.sqlite_wal?.status || "unknown";
  const schemaVer = health?.checks?.migrations?.user_version ?? "?";
  const isOk = health?.status === "ok" && walStatus === "ok";
  pill.className = `badge ${isOk ? "badge-success" : "badge-warning"}`;
  pill.textContent = isOk ? `WAL OK · v${schemaVer}` : `Santé : ${health?.status || "dégradée"}`;
}

function updateSummaryStrip(status) {
  const counts = status?.counts || {};
  updateText("metric-offers", status?.offers_active ?? 0);
  updateText("metric-offers-sub", `Total suivi : ${counts.offers_total ?? 0}`);
  updateText("metric-kits", counts.kits_total ?? 0);
  updateText("metric-profile-sub", status?.profile_configured ? `Preset : ${status.preset_id}` : "Profil à configurer");
  updateText("metric-sent", counts.applications_sent ?? 0);
  updateText(
    "metric-reconcile-sub",
    counts.unreconciled_submissions ? "À réconcilier" : "Réconciliation OK",
  );
  updateText("metric-today", counts.applied_today ?? 0);
  updateText("metric-planned-sub", `Planifiées : ${counts.planned_today ?? 0}`);
}

function handleError(err, prefix = "Erreur API") {
  if (err instanceof ApiError && err.status === 401) {
    setAuthBarOpen(true, "Jeton API requis ou invalide (HTTP 401). Collez le jeton Bearer local.");
    showToast("Authentification requise (HTTP 401).", "warning");
    return;
  }
  const detail = err?.detail || err?.message || "Erreur inattendue";
  showToast(`${prefix} : ${detail}`, "danger");
}

async function refreshChrome() {
  try {
    const health = await careerApi.healthz();
    updateHealthPill(health);
  } catch {
    const pill = document.getElementById("health-pill");
    if (pill) {
      pill.className = "badge badge-danger";
      pill.textContent = "API hors ligne";
    }
  }
  try {
    const status = await careerApi.status(state.token);
    updateSummaryStrip(status);
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      setAuthBarOpen(true, "Authentification requise pour charger les données protégées.");
      return false;
    }
    throw err;
  }
}

async function renderActiveView() {
  const panel = document.getElementById("panel-content");
  if (!panel) return;
  const renderer = VIEW_RENDERERS[state.activeView] || renderOverviewView;
  try {
    await renderer(panel, buildContext());
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      setAuthBarOpen(true, "Saisissez le jeton API Bearer pour accéder à cet onglet.");
      panel.replaceChildren(
        stateBox(
          "error",
          "Authentification requise (HTTP 401).",
          el("button", {
            type: "button",
            className: "btn btn-primary",
            text: "Saisir le jeton",
            on: { click: () => setAuthBarOpen(true) },
          }),
        ),
      );
      return;
    }
    const retryBtn = el("button", {
      type: "button",
      className: "btn btn-secondary",
      text: "Réessayer",
      on: { click: () => refreshAll() },
    });
    panel.replaceChildren(stateBox("error", `Chargement impossible : ${err?.detail || err?.message || err}`, retryBtn));
  }
}

async function refreshAll() {
  const ok = await refreshChrome();
  if (ok) {
    await renderActiveView();
  } else {
    const panel = document.getElementById("panel-content");
    panel?.replaceChildren(
      stateBox(
        "empty",
        "Connectez un jeton Bearer local dans le bandeau ci-dessus pour ouvrir la console.",
      ),
    );
  }
}

function buildContext() {
  return {
    state,
    drawer,
    getToken: () => state.token,
    refreshChrome,
    renderActiveView,
    refreshAll,
    handleError,
  };
}

function setActiveTab(viewName) {
  if (!VIEW_RENDERERS[viewName]) return;
  state.activeView = viewName;
  for (const btn of document.querySelectorAll(".nav-btn[data-view]")) {
    const active = btn.dataset.view === viewName;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", String(active));
  }
  renderActiveView();
}

function bindEvents() {
  for (const btn of document.querySelectorAll(".nav-btn[data-view]")) {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.view));
  }
  document.getElementById("btn-refresh")?.addEventListener("click", () => refreshAll());
  document.getElementById("btn-theme-toggle")?.addEventListener("click", () => {
    const current = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(current);
  });
  document.getElementById("btn-token-toggle")?.addEventListener("click", () => {
    const bar = document.getElementById("auth-bar");
    setAuthBarOpen(Boolean(bar?.hidden));
  });
  document.getElementById("btn-token-clear")?.addEventListener("click", () => {
    state.token = setStoredToken("");
    const input = document.getElementById("token-input");
    if (input) input.value = "";
    showToast("Jeton effacé de la session.", "warning");
    refreshAll();
  });
  document.getElementById("auth-form")?.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const input = document.getElementById("token-input");
    state.token = setStoredToken(input ? input.value : "");
    setAuthBarOpen(false);
    showToast("Jeton de session mis à jour.");
    refreshAll();
  });
}

function bootstrap() {
  initTheme();
  drawer = createDrawerController();
  const input = document.getElementById("token-input");
  if (input && state.token) input.value = state.token;
  bindEvents();
  refreshAll();
}

document.addEventListener("DOMContentLoaded", bootstrap);
