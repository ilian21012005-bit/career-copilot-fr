/** Typed fetch client for all Career Copilot `/api/v1/*` OpenAPI routes. */

const TOKEN_STORAGE_KEY = "career_copilot_token";

export class ApiError extends Error {
  constructor(status, detail, code = "") {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail || `HTTP ${status}`;
    this.code = code || `http_${status}`;
  }
}

export function getStoredToken() {
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function setStoredToken(token) {
  const cleaned = String(token || "").trim();
  try {
    if (cleaned) {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, cleaned);
    } else {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage unavailability in restricted browser contexts.
  }
  return cleaned;
}

export function buildQuery(params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    qs.set(key, String(value));
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

async function parseErrorResponse(response) {
  const text = await response.text();
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object") {
      const detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail || text);
      return new ApiError(response.status, detail.slice(0, 240), String(parsed.code || ""));
    }
  } catch {
    // Non-JSON response fallback.
  }
  return new ApiError(response.status, text.slice(0, 240) || response.statusText);
}

export async function apiRequest(
  path,
  { method = "GET", body = null, token = "", query = null } = {},
) {
  const headers = { Accept: "application/json" };
  const resolvedToken = token || getStoredToken();
  if (resolvedToken) {
    headers.Authorization = `Bearer ${resolvedToken}`;
  }
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  const url = `${path}${query ? buildQuery(query) : ""}`;
  const response = await fetch(url, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return response.json();
}

export async function apiBlobRequest(path, { token = "" } = {}) {
  const headers = { Accept: "application/pdf" };
  const resolvedToken = token || getStoredToken();
  if (resolvedToken) {
    headers.Authorization = `Bearer ${resolvedToken}`;
  }
  const response = await fetch(path, { method: "GET", headers, credentials: "same-origin" });
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return {
    blob: await response.blob(),
    disposition: response.headers.get("Content-Disposition") || "",
  };
}

function enc(value) {
  return encodeURIComponent(String(value));
}

export const careerApi = {
  healthz: () => apiRequest("/healthz"),
  status: (token = "") => apiRequest("/api/v1/status", { token }),
  qualitySummary: (token = "") => apiRequest("/api/v1/quality/summary", { token }),

  listOffers: (token = "", params = {}) =>
    apiRequest("/api/v1/offers", { token, query: params }),
  getOffer: (token = "", offerId) =>
    apiRequest(`/api/v1/offers/${enc(offerId)}`, { token }),
  updateOfferStatus: (token = "", offerId, payload) =>
    apiRequest(`/api/v1/offers/${enc(offerId)}/status`, {
      method: "PATCH",
      token,
      body: payload,
    }),
  getOfferLetter: (token = "", offerId) =>
    apiRequest(`/api/v1/offers/${enc(offerId)}/letter`, { token }),
  getOfferLetterPdf: (token = "", offerId) =>
    apiBlobRequest(`/api/v1/offers/${enc(offerId)}/letter.pdf`, { token }),

  listKits: (token = "", params = {}) =>
    apiRequest("/api/v1/kits", { token, query: params }),

  listApplications: (token = "", params = {}) =>
    apiRequest("/api/v1/applications", { token, query: params }),
  createApplication: (token = "", payload) =>
    apiRequest("/api/v1/applications", { method: "POST", token, body: payload }),
  declareManualApplication: (token = "", payload) =>
    apiRequest("/api/v1/applications/manual", { method: "POST", token, body: payload }),
  withdrawManualApplication: (token = "", offerId, url = "") =>
    apiRequest(`/api/v1/applications/manual/${enc(offerId)}`, {
      method: "DELETE",
      token,
      query: url ? { url } : null,
    }),

  listFollowups: (token = "", params = {}) =>
    apiRequest("/api/v1/followups", { token, query: params }),
  analytics: (token = "") => apiRequest("/api/v1/analytics", { token }),

  listRuns: (token = "", limit = 8) =>
    apiRequest("/api/v1/runs", { token, query: { limit } }),
  getRun: (token = "", runId) =>
    apiRequest(`/api/v1/runs/${enc(runId)}`, { token }),
  triggerDailyRun: (token = "", payload = { auto_submit: false }) =>
    apiRequest("/api/v1/runs/daily", { method: "POST", token, body: payload }),
  triggerSyncRun: (token = "", payload = { source: "imap" }) =>
    apiRequest("/api/v1/runs/sync", { method: "POST", token, body: payload }),

  getInterviewPrep: (token = "", offerId) =>
    apiRequest(`/api/v1/interview-prep/${enc(offerId)}`, { token }),

  getSetup: (token = "") => apiRequest("/api/v1/setup", { token }),
  updateSetup: (token = "", payload) =>
    apiRequest("/api/v1/setup", { method: "PUT", token, body: payload }),
};
