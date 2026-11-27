/** Offers view: filters, status updates, detail/letter/interview drawers. */

import { careerApi } from "./api.js";
import { badge, el, externalLink, formatDate, showToast, stateBox, statusBadge } from "./dom.js";

const OFFER_STATUSES = [
  "new", "shortlist", "prepared", "to_finish", "applied",
  "replied", "interview", "submission_pending", "submission_unknown", "ignored",
];

const offerTrack = (o) => (o.is_alternance ? "Alternance" : o.is_stage ? "Stage" : o.contract || "Job");
const scoreTone = (s) => (s >= 75 ? "success" : s >= 50 ? "warning" : "neutral");
const statusOptions = (cur) => OFFER_STATUSES.map((s) => el("option", { value: s, text: s, selected: s === cur }));
const bulletBlock = (title, items, emptyText = "") => {
  if (!items.length && !emptyText) return null;
  const body = items.length
    ? el("ul", { className: "bullet-list" }, ...items.map((x) => el("li", { text: x })))
    : el("p", { className: "muted", text: emptyText });
  return el("div", { className: "section-block" }, el("h3", { text: title }), body);
};

function buildFilterBar(filters, onApply, onReset) {
  const trackSel = el(
    "select", { id: "f-track", className: "select" },
    el("option", { value: "", text: "Toutes filières", selected: !filters.track }),
    el("option", { value: "stage", text: "Stage", selected: filters.track === "stage" }),
    el("option", { value: "alternance", text: "Alternance", selected: filters.track === "alternance" }),
    el("option", { value: "job", text: "Job étudiant", selected: filters.track === "job" }),
  );
  const statusSel = el(
    "select", { id: "f-status", className: "select" },
    el("option", { value: "", text: "Tous statuts", selected: !filters.status }),
    ...statusOptions(filters.status),
  );
  const queryInput = el("input", {
    id: "f-q", type: "search", className: "input",
    placeholder: "Entreprise, titre, ville…", value: filters.q || "",
  });
  const scoreInput = el("input", {
    id: "f-score", type: "number", min: "0", max: "100", className: "input",
    placeholder: "0", value: filters.min_score ?? "",
  });
  const eligibleCheck = el("input", { id: "f-eligible", type: "checkbox", checked: Boolean(filters.eligible) });

  return el(
    "form",
    {
      className: "toolbar",
      on: {
        submit: (ev) => {
          ev.preventDefault();
          onApply({
            track: trackSel.value,
            status: statusSel.value,
            q: queryInput.value.trim(),
            min_score: scoreInput.value === "" ? "" : Number(scoreInput.value),
            eligible: eligibleCheck.checked,
          });
        },
      },
    },
    el("div", { className: "field" }, el("label", { for: "f-track", text: "Filière" }), trackSel),
    el("div", { className: "field" }, el("label", { for: "f-status", text: "Statut" }), statusSel),
    el("div", { className: "field field-grow" }, el("label", { for: "f-q", text: "Recherche" }), queryInput),
    el("div", { className: "field" }, el("label", { for: "f-score", text: "Score min" }), scoreInput),
    el("label", { className: "field-check" }, eligibleCheck, "Éligibles uniquement"),
    el("button", { type: "submit", className: "btn btn-primary", text: "Filtrer" }),
    el("button", { type: "button", className: "btn btn-ghost", text: "Réinitialiser", on: { click: onReset } }),
  );
}

export async function openLetterDrawer(offerId, ctx) {
  ctx.drawer.open(`Lettre — ${offerId}`, stateBox("loading", "Chargement de la lettre…"));
  try {
    const data = await careerApi.getOfferLetter(ctx.getToken(), offerId);
    const copyBtn = el("button", {
      type: "button", className: "btn btn-primary", text: "Copier la lettre",
      on: {
        click: async () => {
          try {
            await navigator.clipboard.writeText(data.letter);
            showToast("Lettre copiée dans le presse-papiers.");
          } catch {
            showToast("Copie impossible dans ce navigateur.", "warning");
          }
        },
      },
    });
    const pdfBtn = el("button", {
      type: "button", className: "btn btn-secondary", text: "Télécharger PDF",
      on: {
        click: async () => {
          try {
            const { blob } = await careerApi.getOfferLetterPdf(ctx.getToken(), offerId);
            const blobUrl = URL.createObjectURL(blob);
            const a = el("a", { href: blobUrl, download: `lettre-${offerId}.pdf` });
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
          } catch (err) {
            ctx.handleError(err, "PDF indisponible");
          }
        },
      },
    });
    ctx.drawer.open(
      `Lettre — ${offerId}`,
      el(
        "div", null,
        el("p", { className: "muted", text: `Mise à jour : ${formatDate(data.updated_at)}` }),
        el("div", { className: "action-row" }, copyBtn, pdfBtn),
        el("pre", { className: "code-block", text: data.letter }),
      ),
    );
  } catch (err) {
    ctx.drawer.open(`Lettre — ${offerId}`, stateBox("error", err.detail || err.message));
  }
}

export async function openInterviewPrepDrawer(offerId, ctx) {
  ctx.drawer.open("Préparation d'entretien", stateBox("loading", "Génération du brief…"));
  try {
    const prep = await careerApi.getInterviewPrep(ctx.getToken(), offerId);
    ctx.drawer.open(
      `Entretien — ${prep.company}`,
      el(
        "div", null,
        el("p", { className: "cell-title", text: prep.title }),
        el("div", { className: "action-row" }, badge(`${prep.score}/100`, scoreTone(prep.score)), badge(prep.contract || "Contrat", "neutral")),
        bulletBlock("Faits vérifiés correspondants", prep.matched_facts, "Aucun fait associé dans le profil."),
        bulletBlock("Écarts à anticiper", prep.gaps_to_address, "Aucun écart critique relevé."),
        bulletBlock("Questions à préparer", prep.questions_to_prepare, "Aucune question."),
        bulletBlock("Checklist avant entretien", prep.checklist, "Aucune vérification."),
      ),
    );
  } catch (err) {
    ctx.drawer.open("Préparation d'entretien", stateBox("error", err.detail || err.message));
  }
}

export async function openOfferDetailDrawer(offerId, ctx) {
  ctx.drawer.open("Détail de l'offre", stateBox("loading", "Chargement de l'offre…"));
  try {
    const offer = await careerApi.getOffer(ctx.getToken(), offerId);
    const statusSel = el("select", { className: "select", id: "drawer-offer-status" }, ...statusOptions(offer.status));
    const noteInput = el("input", {
      className: "input", id: "drawer-offer-note", type: "text",
      placeholder: "Note opérationnelle…", value: offer.notes || "",
    });
    const statusForm = el(
      "form",
      {
        className: "form-grid",
        on: {
          submit: async (ev) => {
            ev.preventDefault();
            try {
              await careerApi.updateOfferStatus(ctx.getToken(), offer.id, {
                status: statusSel.value, note: noteInput.value.trim(),
              });
              showToast("Statut mis à jour.");
              await ctx.refreshAll();
              await openOfferDetailDrawer(offer.id, ctx);
            } catch (err) {
              ctx.handleError(err, "Mise à jour impossible");
            }
          },
        },
      },
      el("div", { className: "field" }, el("label", { for: "drawer-offer-status", text: "Statut" }), statusSel),
      el("div", { className: "field field-grow" }, el("label", { for: "drawer-offer-note", text: "Note" }), noteInput),
      el("button", { type: "submit", className: "btn btn-primary", text: "Enregistrer" }),
    );

    const links = [
      externalLink(offer.apply_url, "Lien de candidature", "btn btn-secondary btn-sm"),
      externalLink(offer.ats_url, "Portail ATS", "btn btn-secondary btn-sm"),
      externalLink(offer.url, "Annonce source", "btn btn-ghost btn-sm"),
    ].filter(Boolean);

    const runOfferMutation = async (fn, successMsg, errLabel) => {
      try {
        const res = await fn();
        showToast(typeof successMsg === "function" ? successMsg(res) : successMsg);
        await ctx.refreshAll();
        await openOfferDetailDrawer(offer.id, ctx);
      } catch (err) {
        ctx.handleError(err, errLabel);
      }
    };
    const textBlock = (heading, val) =>
      val ? el("div", { className: "section-block" }, el("h3", { text: heading }), el("p", { text: val })) : null;

    ctx.drawer.open(
      `${offer.company || "Entreprise"} — ${offer.title}`,
      el(
        "div", null,
        el(
          "div", { className: "action-row" },
          badge(`${offer.score}/100`, scoreTone(offer.score)),
          statusBadge(offer.status),
          badge(offerTrack(offer), "neutral"),
          offer.has_kit ? badge("Dossier prêt", "success") : null,
        ),
        el("p", {
          className: "cell-meta",
          text: `${offer.city || "Ville n/c"}${offer.zone ? ` · Zone ${offer.zone}` : ""}${offer.distance_km != null ? ` · ${offer.distance_km} km` : ""} · Vu : ${formatDate(offer.last_seen)}`,
        }),
        links.length ? el("div", { className: "action-row" }, ...links) : null,
        el("div", { className: "section-block" }, el("h3", { text: "Changer le statut" }), statusForm),
        el(
          "div", { className: "section-block action-row" },
          el("button", {
            type: "button", className: "btn btn-primary btn-sm", text: "Déclarer manuelle",
            on: {
              click: () => runOfferMutation(
                () => careerApi.declareManualApplication(ctx.getToken(), {
                  offer_id: offer.id, channel: "candidature-manuelle", note: noteInput.value.trim(),
                }),
                (r) => (r.changed ? "Candidature manuelle enregistrée." : "Candidature déjà enregistrée."),
                "Déclaration refusée",
              ),
            },
          }),
          el("button", {
            type: "button", className: "btn btn-danger btn-sm", text: "Retirer manuelle",
            on: {
              click: () => runOfferMutation(
                () => careerApi.withdrawManualApplication(ctx.getToken(), offer.id),
                "Déclaration manuelle retirée.", "Retrait impossible",
              ),
            },
          }),
          el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Lettre", on: { click: () => openLetterDrawer(offer.id, ctx) } }),
          el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Entretien", on: { click: () => openInterviewPrepDrawer(offer.id, ctx) } }),
        ),
        bulletBlock("Points forts", offer.reasons),
        bulletBlock("Écarts", offer.gaps),
        textBlock("Missions", offer.missions),
        textBlock("Profil recherché", offer.profile),
        textBlock("Description", offer.description),
      ),
    );
  } catch (err) {
    ctx.drawer.open("Détail de l'offre", stateBox("error", err.detail || err.message));
  }
}

export async function renderOffersView(container, ctx) {
  container.replaceChildren(stateBox("loading", "Chargement des offres…"));
  const f = ctx.state.offerFilters;
  const data = await careerApi.listOffers(ctx.getToken(), {
    track: f.track, status: f.status, q: f.q, min_score: f.min_score,
    eligible: f.eligible ? true : "", limit: 50,
  });

  const head = el(
    "div", { className: "section-head" },
    el("div", null, el("h1", { text: "Offres suivies" }), el("p", { className: "muted", text: `${data.total} résultat(s) correspondant aux filtres.` })),
  );
  const filterBar = buildFilterBar(
    f,
    (next) => { ctx.state.offerFilters = next; ctx.renderActiveView(); },
    () => { ctx.state.offerFilters = { track: "", status: "", q: "", min_score: "", eligible: false }; ctx.renderActiveView(); },
  );

  if (!data.items.length) {
    container.replaceChildren(head, filterBar, stateBox("empty", "Aucune offre ne correspond à ces critères."));
    return;
  }

  const rows = data.items.map((offer) => {
    const inlineStatus = el(
      "select",
      {
        className: "select",
        "aria-label": `Statut de ${offer.title}`,
        on: {
          change: async () => {
            try {
              await careerApi.updateOfferStatus(ctx.getToken(), offer.id, { status: inlineStatus.value, note: offer.notes || "" });
              showToast(`Statut mis à jour : ${inlineStatus.value}`);
              await ctx.refreshChrome();
            } catch (err) {
              inlineStatus.value = offer.status;
              ctx.handleError(err, "Changement de statut refusé");
            }
          },
        },
      },
      ...statusOptions(offer.status),
    );
    return el(
      "tr", null,
      el("td", null, badge(`${offer.score}/100`, scoreTone(offer.score))),
      el("td", null, el("div", { className: "cell-title", text: offer.title || "Poste sans titre" }), el("div", { className: "cell-meta", text: `${offer.company || "Entreprise n/c"} · ${offer.city || "Ville n/c"}${offer.zone ? ` (${offer.zone})` : ""}` })),
      el("td", null, badge(offerTrack(offer), "neutral"), offer.has_kit ? el("div", { className: "cell-meta" }, badge("Dossier", "success")) : null),
      el("td", null, inlineStatus),
      el("td", null, el("div", { className: "cell-actions" }, el("button", { type: "button", className: "btn btn-secondary btn-sm", text: "Détail", on: { click: () => openOfferDetailDrawer(offer.id, ctx) } }), el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "Lettre", on: { click: () => openLetterDrawer(offer.id, ctx) } }), el("button", { type: "button", className: "btn btn-ghost btn-sm", text: "Entretien", on: { click: () => openInterviewPrepDrawer(offer.id, ctx) } }))),
    );
  });

  const table = el(
    "div", { className: "table-wrap" },
    el(
      "table", { className: "data-table" },
      el("thead", null, el("tr", null, ...["Score", "Offre", "Filière", "Statut", "Actions"].map((h) => el("th", { text: h })))),
      el("tbody", null, ...rows),
    ),
  );
  container.replaceChildren(head, filterBar, table);
}
