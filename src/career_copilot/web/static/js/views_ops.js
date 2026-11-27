/** Operational views: overview, applications/followups, kits, runs/analytics, setup. */

import { careerApi } from "./api.js";
import { badge, el, externalLink, formatDate, showToast, stateBox, statusBadge } from "./dom.js";
import { openLetterDrawer, openOfferDetailDrawer } from "./views_offers.js";

const PRESETS = [
  ["it_infra_cyber", "IT Infra, Réseaux & Cyber"],
  ["software_data", "Développement & Data"],
  ["engineering_industry", "Ingénierie & Industrie"],
  ["business_marketing", "Commerce & Marketing"],
  ["student_job_only", "Job étudiant uniquement"],
];

const CONTRACTS = [
  ["stage", "Stage"],
  ["alternance", "Alternance"],
  ["job", "Job étudiant"],
];

function makeTable(headers, rows) {
  return el(
    "div", { className: "table-wrap" },
    el(
      "table", { className: "data-table" },
      el("thead", null, el("tr", null, ...headers.map((h) => el("th", { text: h })))),
      el("tbody", null, ...rows),
    ),
  );
}

async function triggerDailyAction(ctx, autoSubmit = false) {
  try {
    const res = await careerApi.triggerDailyRun(ctx.getToken(), { auto_submit: autoSubmit });
    showToast(`Cycle quotidien #${res.run_id} démarré (${res.status}).`);
    await ctx.refreshAll();
  } catch (err) {
    ctx.handleError(err, "Cycle quotidien refusé");
  }
}

async function triggerSyncAction(ctx) {
  try {
    const res = await careerApi.triggerSyncRun(ctx.getToken(), { source: "imap" });
    showToast(`Synchronisation #${res.run_id} : ${res.synced_messages} message(s).`);
    await ctx.refreshAll();
  } catch (err) {
    ctx.handleError(err, "Synchronisation échouée");
  }
}

async function openRunDetailDrawer(runId, ctx) {
  ctx.drawer.open(`Cycle #${runId}`, stateBox("loading", "Chargement du détail…"));
  try {
    const run = await careerApi.getRun(ctx.getToken(), runId);
    ctx.drawer.open(
      `Cycle #${run.run_id} (${run.kind})`,
      el(
        "div", null,
        el("div", { className: "action-row" }, statusBadge(run.status), badge(run.kind, "neutral")),
        el("p", { className: "cell-meta", text: `Début : ${formatDate(run.started_at)} · Fin : ${formatDate(run.finished_at)}` }),
        run.duration_seconds != null ? el("p", { text: `Durée : ${run.duration_seconds.toFixed(1)} s` }) : null,
        run.synced_messages ? el("p", { text: `Messages synchronisés : ${run.synced_messages}` }) : null,
        run.error_code ? el("p", { className: "muted", text: `Code erreur : ${run.error_code}` }) : null,
        el("pre", { className: "code-block", text: run.summary || "Aucun résumé enregistré." }),
      ),
    );
  } catch (err) {
    ctx.drawer.open(`Cycle #${runId}`, stateBox("error", err.detail || err.message));
  }
}

function renderStatusBars(buckets) {
  if (!buckets.length) return stateBox("empty", "Aucune répartition de statut disponible.");
  const maxVal = Math.max(1, ...buckets.map((b) => Number(b.value || 0)));
  return el(
    "div", null,
    ...buckets.map((b) => {
      const pct = Math.round((Number(b.value || 0) / maxVal) * 100);
      return el("div", { className: "bar-row" }, el("span", { className: "muted", text: b.label }), el("div", { className: "bar-track" }, el("div", { className: "bar-fill", style: `width:${pct}%` })), el("strong", { text: String(b.value) }));
    }),
  );
}

export async function renderOverviewView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement de la vue d'ensemble…"));
  const token = ctx.getToken();
  const [quality, followups, analytics, runs] = await Promise.all([
    careerApi.qualitySummary(token),
    careerApi.listFollowups(token, { due_only: true }),
    careerApi.analytics(token),
    careerApi.listRuns(token, 5),
  ]);

  const issuesBlock = quality.issues.length
    ? el("ul", { className: "record-list" }, ...quality.issues.map((i) => el("li", { className: "record-item" }, el("div", null, el("strong", { text: i.detail }), el("div", { className: "cell-meta", text: `${i.kind} · occurrences : ${i.count}` })), statusBadge(i.severity))))
    : stateBox("empty", "Aucune anomalie qualité détectée.");

  const dueBlock = followups.candidates.length
    ? el("ul", { className: "record-list" }, ...followups.candidates.slice(0, 6).map((c) => el("li", { className: "record-item" }, el("div", null, el("div", { className: "cell-title", text: `${c.company || "Entreprise"} — ${c.title}` }), el("div", { className: "cell-meta", text: `Envoyée il y a ${c.days_since_application} j (${c.applied_date || formatDate(c.applied_at)})` })), el("div", { className: "action-row" }, badge("Relance due", "warning"), c.offer_id ? el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Offre", on: { click: () => openOfferDetailDrawer(c.offer_id, ctx) } }) : null))))
    : stateBox("empty", "Aucune relance urgente aujourd'hui.");

  const freshnessList = el("ul", { className: "record-list" }, ...analytics.freshness.map((f) => el("li", { className: "record-item" }, el("span", { text: `${f.label}${f.age_hours != null ? ` (${f.age_hours.toFixed(1)} h)` : ""}` }), statusBadge(f.status))));
  const runsList = runs.runs.length
    ? el("ul", { className: "record-list" }, ...runs.runs.map((r) => el("li", { className: "record-item" }, el("div", null, el("strong", { text: `#${r.id} · ${r.kind}` }), el("div", { className: "cell-meta", text: `${formatDate(r.started_at)} · ${r.summary || "Sans résumé"}` })), el("div", { className: "action-row" }, statusBadge(r.status), el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "Détail", on: { click: () => openRunDetailDrawer(r.id, ctx) } })))))
    : stateBox("empty", "Aucun cycle exécuté.");

  container.replaceChildren(
    el(
      "div", { className: "section-head" },
      el("div", null, el("h1", { text: "Vue d'ensemble opérationnelle" }), el("p", { className: "muted", text: `Relances dues : ${followups.count_due} · Réponses : ${analytics.kpis.reply_total} · 7j : ${quality.metrics.applications_7d} candidature(s)` })),
      el("div", { className: "action-row" }, el("button", { type: "button", className: "btn btn-primary", text: "Lancer cycle quotidien", on: { click: () => triggerDailyAction(ctx, false) } }), el("button", { type: "button", className: "btn btn-secondary", text: "Synchroniser IMAP", on: { click: () => triggerSyncAction(ctx) } })),
    ),
    el("div", { className: "split-grid" }, el("div", { className: "card-box" }, el("h2", { text: "Urgences qualité" }), issuesBlock), el("div", { className: "card-box" }, el("h2", { text: "Relances à traiter" }), dueBlock)),
    el("div", { className: "section-block split-grid" }, el("div", { className: "card-box" }, el("h2", { text: "Fraîcheur & statut" }), freshnessList), el("div", { className: "card-box" }, el("h2", { text: "Derniers cycles" }), runsList)),
  );
}

export async function renderApplicationsView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement des candidatures…"));
  const token = ctx.getToken();
  const [apps, followups] = await Promise.all([
    careerApi.listApplications(token, { since_days: ctx.state.appSinceDays, limit: 80 }),
    careerApi.listFollowups(token, { due_only: false }),
  ]);

  const offerIdInput = el("input", { id: "m-offer", className: "input", placeholder: "ID offre ou vide si URL" });
  const urlInput = el("input", { id: "m-url", className: "input", type: "url", placeholder: "https://…" });
  const noteInput = el("input", { id: "m-note", className: "input", placeholder: "Preuve ou commentaire…" });
  const manualForm = el(
    "form",
    {
      className: "toolbar",
      on: {
        submit: async (ev) => {
          ev.preventDefault();
          const offer_id = offerIdInput.value.trim() || null;
          const url = urlInput.value.trim() || null;
          if (!offer_id && !url) { showToast("Renseignez un ID d'offre ou une URL.", "warning"); return; }
          try {
            const res = await careerApi.declareManualApplication(token, { offer_id, url, channel: "candidature-manuelle", note: noteInput.value.trim() });
            showToast(res.changed ? "Candidature manuelle déclarée." : "Déjà enregistrée.");
            await ctx.refreshAll();
          } catch (err) {
            ctx.handleError(err, "Déclaration refusée");
          }
        },
      },
    },
    el("div", { className: "field" }, el("label", { for: "m-offer", text: "ID offre" }), offerIdInput),
    el("div", { className: "field field-grow" }, el("label", { for: "m-url", text: "URL annonce" }), urlInput),
    el("div", { className: "field field-grow" }, el("label", { for: "m-note", text: "Note" }), noteInput),
    el("button", { type: "submit", className: "btn btn-primary", text: "Déclarer" }),
  );

  const appTable = apps.items.length
    ? makeTable(
        ["Entreprise & Poste", "Canal & Date", "Preuve", "Actions"],
        apps.items.map((item) => el(
          "tr", null,
          el("td", null, el("div", { className: "cell-title", text: `${item.company || "Entreprise"} — ${item.title || item.offer_id}` }), externalLink(item.url, "Ouvrir l'annonce", "cell-meta")),
          el("td", null, badge(item.channel || "—", "neutral"), el("div", { className: "cell-meta", text: formatDate(item.applied_at) })),
          el("td", null, item.has_proof ? badge(item.proof_kind, "success") : badge(item.manual ? "Manuelle" : "Sans preuve", "warning"), item.evidence ? el("div", { className: "cell-meta", text: item.evidence }) : null),
          el("td", null, el("div", { className: "cell-actions" }, item.offer_id ? el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Offre", on: { click: () => openOfferDetailDrawer(item.offer_id, ctx) } }) : null, item.manual && item.offer_id ? el("button", {
            type: "button", className: "btn btn-danger btn-sm", text: "Retirer",
            on: {
              click: async () => {
                try { await careerApi.withdrawManualApplication(token, item.offer_id, item.url); showToast("Candidature manuelle retirée."); await ctx.refreshAll(); } catch (err) { ctx.handleError(err, "Retrait refusé"); }
              },
            },
          }) : null)),
        )),
      )
    : stateBox("empty", "Aucune candidature enregistrée sur cette période.");

  const followupList = followups.candidates.length
    ? el("ul", { className: "record-list" }, ...followups.candidates.map((c) => el("li", { className: "record-item" }, el("div", null, el("strong", { text: `${c.company || "Entreprise"} — ${c.title}` }), el("div", { className: "cell-meta", text: `J+${c.days_since_application} · ${c.applied_date || formatDate(c.applied_at)}` })), badge(c.is_due ? "À relancer" : "En attente", c.is_due ? "warning" : "neutral"))))
    : stateBox("empty", "Aucune relance suivie.");

  container.replaceChildren(
    el("div", { className: "section-head" }, el("div", null, el("h1", { text: "Candidatures & Relances" }), el("p", { className: "muted", text: `${apps.total} candidature(s) · Aujourd'hui : ${apps.applied_today} · Relances dues : ${followups.count_due}` }))),
    manualForm, appTable,
    el("div", { className: "section-block" }, el("h2", { text: "Suivi des relances" }), followupList),
  );
}

export async function renderKitsView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement des dossiers…"));
  const kits = await careerApi.listKits(ctx.getToken(), { ready_only: ctx.state.kitsReadyOnly ? true : "", limit: 100 });
  const toggleCheck = el("input", {
    type: "checkbox", checked: Boolean(ctx.state.kitsReadyOnly),
    on: { change: () => { ctx.state.kitsReadyOnly = toggleCheck.checked; ctx.renderActiveView(); } },
  });
  const head = el("div", { className: "section-head" }, el("div", null, el("h1", { text: "Dossiers de candidature" }), el("p", { className: "muted", text: `${kits.total} dossier(s) disponible(s).` })), el("label", { className: "field-check" }, toggleCheck, "Complets (CV + Lettre) uniquement"));
  if (!kits.items.length) {
    container.replaceChildren(head, stateBox("empty", "Aucun dossier généré pour ce filtre."));
    return;
  }
  const table = makeTable(
    ["Offre", "Pièces", "Mise à jour", "Actions"],
    kits.items.map((k) => el(
      "tr", null,
      el("td", null, el("div", { className: "cell-title", text: `${k.company || "Entreprise"} — ${k.title || k.offer_id}` }), el("div", { className: "cell-meta", text: k.subject || k.offer_id })),
      el("td", null, el("div", { className: "cell-actions" }, badge("CV", k.has_cv ? "success" : "neutral"), badge("Lettre", k.has_letter ? "success" : "neutral"), badge("Dossier", k.has_dossier ? "success" : "neutral"), k.is_current ? badge("À jour", "accent") : badge("Ancien", "warning"))),
      el("td", { text: formatDate(k.updated_at || k.created_at) }),
      el("td", null, el("div", { className: "cell-actions" }, el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Lettre", on: { click: () => openLetterDrawer(k.offer_id, ctx) } }), el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "Offre", on: { click: () => openOfferDetailDrawer(k.offer_id, ctx) } }))),
    )),
  );
  container.replaceChildren(head, table);
}

export async function renderRunsView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement des cycles et analytiques…"));
  const token = ctx.getToken();
  const [runs, analytics, quality] = await Promise.all([
    careerApi.listRuns(token, 15),
    careerApi.analytics(token),
    careerApi.qualitySummary(token),
  ]);
  const autoSubmitCheck = el("input", { type: "checkbox", id: "run-autosubmit" });
  const runsTable = runs.runs.length
    ? makeTable(
        ["ID", "Type", "Statut", "Démarré", "Résumé", "Action"],
        runs.runs.map((r) => el("tr", null, el("td", { className: "mono", text: `#${r.id}` }), el("td", { text: r.kind }), el("td", null, statusBadge(r.status)), el("td", { text: formatDate(r.started_at) }), el("td", { text: r.summary || "—" }), el("td", null, el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Inspecter", on: { click: () => openRunDetailDrawer(r.id, ctx) } })))),
      )
    : stateBox("empty", "Aucun cycle enregistré.");

  container.replaceChildren(
    el("div", { className: "section-head" }, el("div", null, el("h1", { text: "Cycles & Analytique" }), el("p", { className: "muted", text: `Offres : ${analytics.kpis.offers_total} · Candidatures : ${analytics.kpis.applications_total} · Réponses : ${analytics.kpis.reply_total} · Anomalies : ${quality.issues.length}` })), el("div", { className: "action-row" }, el("label", { className: "field-check" }, autoSubmitCheck, "Auto-envoi"), el("button", { type: "button", className: "btn btn-primary", text: "Déclencher cycle quotidien", on: { click: () => triggerDailyAction(ctx, autoSubmitCheck.checked) } }), el("button", { type: "button", className: "btn btn-secondary", text: "Synchroniser IMAP", on: { click: () => triggerSyncAction(ctx) } }))),
    runsTable,
    el("div", { className: "section-block split-grid" }, el("div", { className: "card-box" }, el("h2", { text: "Répartition des statuts" }), renderStatusBars(analytics.application_statuses)), el("div", { className: "card-box" }, el("h2", { text: "Fraîcheur des connecteurs" }), el("ul", { className: "record-list" }, ...analytics.freshness.map((f) => el("li", { className: "record-item" }, el("span", { text: f.label }), statusBadge(f.status)))))),
  );
}

export async function renderSetupView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement du profil…"));
  const token = ctx.getToken();
  const setup = await careerApi.getSetup(token);
  const presetSel = el("select", { id: "s-preset", className: "select" }, ...PRESETS.map(([id, label]) => el("option", { value: id, text: label, selected: id === setup.preset })));
  const contractChecks = CONTRACTS.map(([id, label]) => {
    const input = el("input", { type: "checkbox", value: id, checked: setup.contracts.includes(id) });
    return { id, input, node: el("label", { className: "field-check" }, input, label) };
  });
  const zoneInput = el("input", { id: "s-zone", className: "input", value: setup.zone_preset || "standalone_example" });
  const radiusInput = el("input", { id: "s-radius", className: "input", type: "number", min: "1", max: "150", value: String(setup.job_radius_km) });
  const minScoreInput = el("input", { id: "s-minscore", className: "input", type: "number", min: "0", max: "100", value: String(setup.min_score) });
  const targetInput = el("input", { id: "s-target", className: "input", type: "number", min: "1", max: "50", value: String(setup.daily_target) });
  const maxInput = el("input", { id: "s-max", className: "input", type: "number", min: "1", max: "50", value: String(setup.daily_max) });
  const factsArea = el("textarea", { id: "s-facts", className: "textarea", placeholder: "Optionnel : 1 fait vérifié par ligne (laisser vide pour conserver les faits actuels)." });

  const form = el(
    "form",
    {
      className: "card-box",
      on: {
        submit: async (ev) => {
          ev.preventDefault();
          const contracts = contractChecks.filter((c) => c.input.checked).map((c) => c.id);
          if (!contracts.length) { showToast("Sélectionnez au moins un type de contrat.", "warning"); return; }
          const payload = {
            preset: presetSel.value, contracts,
            zone_preset: zoneInput.value.trim() || "standalone_example",
            job_radius_km: Number(radiusInput.value),
            preferences: { min_score: Number(minScoreInput.value), daily_target: Number(targetInput.value), daily_max: Number(maxInput.value) },
          };
          const rawFacts = factsArea.value.split("\n").map((l) => l.trim()).filter(Boolean);
          if (rawFacts.length) payload.facts = rawFacts;
          try {
            await careerApi.updateSetup(token, payload);
            showToast("Profil enregistré (mode privé 0600).");
            await ctx.refreshAll();
          } catch (err) {
            ctx.handleError(err, "Enregistrement du profil refusé");
          }
        },
      },
    },
    el("div", { className: "form-grid" }, el("div", { className: "field field-grow" }, el("label", { for: "s-preset", text: "Preset métier" }), presetSel), el("div", { className: "field field-grow" }, el("label", { for: "s-zone", text: "Preset de zone" }), zoneInput)),
    el("div", { className: "section-block action-row" }, ...contractChecks.map((c) => c.node)),
    el("div", { className: "section-block form-grid" }, el("div", { className: "field" }, el("label", { for: "s-radius", text: "Rayon job (km)" }), radiusInput), el("div", { className: "field" }, el("label", { for: "s-minscore", text: "Score min" }), minScoreInput), el("div", { className: "field" }, el("label", { for: "s-target", text: "Cible / jour" }), targetInput), el("div", { className: "field" }, el("label", { for: "s-max", text: "Plafond / jour" }), maxInput)),
    el("div", { className: "section-block field" }, el("label", { for: "s-facts", text: "Faits vérifiés du candidat (optionnel)" }), factsArea),
    el("div", { className: "section-block action-row" }, el("button", { type: "submit", className: "btn btn-primary", text: "Enregistrer le profil" })),
  );

  container.replaceChildren(
    el("div", { className: "section-head" }, el("div", null, el("h1", { text: "Profil & Préférences" }), el("p", { className: "muted", text: `Schéma v${setup.schema_version} · ${setup.facts_count} fait(s) · ${setup.skills_count} compétence(s) · ${setup.zones.length} zone(s)` })), badge(setup.configured ? "Profil configuré" : "Non configuré", setup.configured ? "success" : "warning")),
    setup.load_error ? stateBox("error", setup.load_error) : null,
    form,
  );
}
