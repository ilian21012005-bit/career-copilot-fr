"""Tableau de bord local : ce qui est prêt, ce qui est envoyé, ce qui reste."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from config import DATA_DIR
from private_storage import ensure_private_directory, write_private_text

from . import store

REPORT_DIR = DATA_DIR / "hellowork"

LABELS = {
    "new": "nouvelle",
    "shortlist": "retenue",
    "prepared": "dossier prêt",
    "applied": "envoyée",
    "to_finish": "à finir chez le recruteur",
    "replied": "réponse reçue",
    "interview": "entretien",
    "ignored": "écartée",
}


def build(min_score: int = 0) -> dict:
    ensure_private_directory(REPORT_DIR)
    rows = store.list_offers(min_score=min_score, limit=300)
    stats = store.stats()
    plan = store.plan_for()
    md = REPORT_DIR / "rapport.md"
    page = REPORT_DIR / "rapport.html"
    write_private_text(md, _markdown(rows, stats, plan))
    write_private_text(page, _html(rows, stats, plan))
    plan_page = write_plan(plan)
    return {
        "markdown": md,
        "html": page,
        "plan": plan_page,
        "stats": stats,
        "rows": len(rows),
        "plan_rows": len(plan),
    }


def write_plan(rows=None) -> Path:
    """Écrit la file du jour : une page HTML cliquable pour vérifier et envoyer."""
    rows = list(rows) if rows is not None else store.plan_for()
    ensure_private_directory(REPORT_DIR)
    path = REPORT_DIR / "plan.html"
    write_private_text(path, _plan_html(rows))
    return path


def _markdown(rows, stats, plan=None) -> str:
    today = stats["aujourd'hui"]
    lines = [
        "# HelloWork — tableau de bord",
        "",
        f"Mis à jour le {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}",
        "",
        f"- Offres connues : {stats['offres']}",
        f"- Dossiers prêts : {stats['dossiers']}",
        f"- Candidatures enregistrées : {stats['candidatures']}",
        f"- Envoyées aujourd'hui : {today}",
    ]
    if plan:
        lines += ["", f"## File du jour — {len(plan)} candidature(s)", ""]
        for row in plan:
            kit = store.kit_for(row["id"])
            letter = f" · [lettre]({_uri(kit['letter_path'])})" if kit and kit["letter_path"] else ""
            lines.append(
                f"- [ ] {row['position']}. **{_md(row['company'])}** — [{_md(row['title'])}]({row['url']}) "
                f"({row['score']}/100 · {_md(row['city'] or '')}){letter}  \n"
                f"  `python -m hellowork confirm {row['id']}` · `python -m hellowork skip {row['id']}`"
            )
    lines += [
        "",
        "| Score | Entreprise | Poste | Lieu | Statut |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['score']} | {_md(row['company'])} | [{_md(row['title'])}]({row['url']}) "
            f"| {_md(row['city'])}{(' (' + row['department'] + ')') if row['department'] else ''} "
            f"| {LABELS.get(row['status'], row['status'])} |"
        )
    if not rows:
        lines.append("| — | — | — | — | aucune offre enregistrée |")
    lines += [
        "",
        "La tâche quotidienne peut envoyer automatiquement les offres éligibles.",
        "`python -m hellowork sync` lit les confirmations HelloWork ;",
        "`python -m hellowork confirm <id>` enregistre un envoi vérifié manuellement.",
    ]
    return "\n".join(lines) + "\n"


def _md(text: str) -> str:
    return (text or "").replace("|", "\\|")


def _uri(path: str) -> str:
    if not path:
        return "#"
    try:
        return Path(path).resolve().as_uri()
    except Exception:
        return "#"


def _html(rows, stats, plan=None) -> str:
    body_rows = []
    for row in rows:
        status = LABELS.get(row["status"], row["status"])
        place = row["city"] or ""
        if row["department"]:
            place = f"{place} ({row['department']})" if place else row["department"]
        body_rows.append(
            f"""<tr>
      <td class="score s{_bucket(row['score'])}">{row['score']}</td>
      <td><strong>{html.escape(row['company'] or '—')}</strong></td>
      <td><a href="{html.escape(row['url'] or '#')}" target="_blank" rel="noreferrer">{html.escape(row['title'] or '—')}</a></td>
      <td>{html.escape(place)}</td>
      <td><span class="tag">{html.escape(status)}</span></td>
    </tr>"""
        )
    table = "\n".join(body_rows) or '<tr><td colspan="5">Aucune offre enregistrée.</td></tr>'
    cards = "".join(
        f'<div class="card"><span class="num">{value}</span><span class="label">{html.escape(str(key))}</span></div>'
        for key, value in stats.items()
    )
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<title>HelloWork — tableau de bord</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 32px; background: #f6f5f2; color: #1b1b1b; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  p.sub {{ margin: 0 0 24px; color: #666; font-size: 13px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px; }}
  .card {{ background: #fff; border: 1px solid #e3e1dc; border-radius: 10px; padding: 14px 18px; min-width: 120px; }}
  .card .num {{ display: block; font-size: 26px; font-weight: 600; }}
  .card .label {{ font-size: 12px; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #e3e1dc; border-radius: 10px; overflow: hidden; font-size: 14px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #efeeea; vertical-align: top; }}
  th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #777; background: #fbfaf8; }}
  tr:last-child td {{ border-bottom: none; }}
  a {{ color: #4338ca; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .score {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
  .s80, .s90, .s100 {{ color: #15803d; }}
  .s60, .s70 {{ color: #a16207; }}
  .s0, .s10, .s20, .s30, .s40, .s50 {{ color: #b91c1c; }}
  .tag {{ background: #eeede8; border-radius: 999px; padding: 3px 9px; font-size: 12px; }}
  footer {{ margin-top: 20px; font-size: 12px; color: #777; line-height: 1.5; }}
</style>
</head>
<body>
  <h1>HelloWork — tableau de bord</h1>
  <p class="sub">Mis à jour le {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}. Le bot prépare, vous envoyez.</p>
  <div class="cards">{cards}</div>
  {_plan_section(plan)}
  <table>
    <thead><tr><th>Score</th><th>Entreprise</th><th>Poste</th><th>Lieu</th><th>Statut</th></tr></thead>
    <tbody>
    {table}
    </tbody>
  </table>
  <footer>
    Score calculé sur le contrat, le lieu, les compétences, le niveau demandé et la fraîcheur de l'annonce.<br />
    Une offre à moins de 80/100 n'est pas préparée : mieux vaut dix candidatures justes que cinquante génériques.
  </footer>
</body>
</html>
"""


def _bucket(score: int) -> int:
    return max(0, min(100, (int(score) // 10) * 10))


def _plan_section(plan) -> str:
    if not plan:
        return ""
    rows = []
    for row in plan:
        kit = store.kit_for(row["id"])
        letter_link = ""
        if kit and kit["letter_path"]:
            letter_link = (
                f'<a href="{html.escape(_uri(kit["letter_path"]))}">lettre</a> · '
            )
        status = row["plan_status"]
        tag = "ok" if status == "applied" else ("skip" if status == "skipped" else "todo")
        where = html.escape(row["city"] or "")
        if row["zone"] and row["distance_km"] is not None:
            where += (
                f'<br><span class="muted">{html.escape(row["zone"])} · '
                f'{row["distance_km"]:.0f} km</span>'
            )
        rows.append(
            f"""<tr>
      <td class="pos">{row['position']}</td>
      <td class="score s{_bucket(row['score'])}">{row['score']}</td>
      <td><strong>{html.escape(row['company'] or '—')}</strong><br>
          <span class="muted">{html.escape(row['title'] or '')}</span></td>
      <td>{where}</td>
      <td class="actions">{letter_link}
          <a href="{html.escape(row['url'] or '#')}" target="_blank" rel="noreferrer">ouvrir l'offre</a><br>
          <code>python -m hellowork confirm {row['id']}</code><br>
          <code>python -m hellowork skip {row['id']}</code></td>
      <td><span class="tag tag-{tag}">{html.escape(status)}</span></td>
    </tr>"""
        )
    body = "\n".join(rows) or '<tr><td colspan="6">File vide — `python -m hellowork plan`.</td></tr>'
    return f"""<h2>File du jour</h2>
  <table>
    <thead><tr><th>#</th><th>Score</th><th>Entreprise / poste</th><th>Lieu</th><th>Actions</th><th>État</th></tr></thead>
    <tbody>
    {body}
    </tbody>
  </table>"""


def _plan_html(rows) -> str:
    body = ""
    for row in rows:
        kit = store.kit_for(row["id"])
        letter = ""
        if kit and kit["letter_path"]:
            letter = f'<a href="{html.escape(_uri(kit["letter_path"]))}" class="btn">Lettre</a>'
        place = row["city"] or ""
        if row["department"]:
            place = f"{place} ({row['department']})" if place else row["department"]
        if row["zone"] and row["distance_km"] is not None:
            place += f" · {row['zone']} · {row['distance_km']:.0f} km"
        elif (row["location_status"] or "") == "unknown":
            place += " · localisation à vérifier"
        status = row["plan_status"]
        state = {
            'applied': '✅ envoyée', 'skipped': '⏭️ écartée',
            'submission_unknown': '⚠️ envoi à vérifier avant toute reprise',
            'submission_pending': '⏳ en cours de transmission',
            'to_finish': 'à finaliser chez le recruteur',
        }.get(status, 'à traiter')
        body += f"""<div class="row">
    <div class="idx">{row['position']}</div>
    <div class="main">
      <div class="score s{_bucket(row['score'])}">{row['score']}/100</div>
      <div class="title"><strong>{html.escape(row['company'] or '—')}</strong> — {html.escape(row['title'] or '')}</div>
      <div class="muted">{html.escape(place)} · {html.escape(state)}</div>
      <div class="cmds">
        <code>python -m hellowork confirm {row['id']}</code>
        <code>python -m hellowork skip {row['id']}</code>
      </div>
    </div>
    <div class="side">
      <a href="{html.escape(row['url'] or '#')}" target="_blank" rel="noreferrer" class="btn">Ouvrir l'offre</a>
      {letter}
    </div>
  </div>"""
    if not body:
        body = (
            '<div class="empty">File vide.<br>'
            "Deux causes possibles : aucune alerte HelloWork n'a encore envoyé d'offre "
            "(ouvre <code>data/hellowork/alertes.html</code> pour les créer), ou les offres "
            "reçues ne passent pas le seuil de 80/100 (voir <code>rapport.html</code>)."
            "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<title>HelloWork — file du jour</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 32px; background: #f6f5f2; color: #1b1b1b; }}
  h1 {{ font-size: 22px; }}
  p.sub {{ color: #666; font-size: 13px; margin: 0 0 24px; }}
  .row {{ display: flex; gap: 16px; background: #fff; border: 1px solid #e3e1dc; border-radius: 12px; padding: 16px 18px; margin-bottom: 12px; align-items: flex-start; }}
  .idx {{ font-size: 20px; font-weight: 700; color: #999; min-width: 28px; }}
  .main {{ flex: 1; }}
  .side {{ display: flex; flex-direction: column; gap: 8px; align-items: flex-end; }}
  .title {{ font-size: 15px; }}
  .muted {{ color: #777; font-size: 13px; margin-top: 2px; }}
  .cmds {{ margin-top: 8px; }}
  code {{ background: #f0efe9; border-radius: 6px; padding: 2px 7px; font-size: 12px; margin-right: 8px; }}
  .score {{ display: inline-block; font-weight: 700; font-variant-numeric: tabular-nums; margin-right: 8px; }}
  .s80, .s90, .s100 {{ color: #15803d; }}
  .s60, .s70 {{ color: #a16207; }}
  .btn {{ background: #111; color: #fff; border-radius: 8px; padding: 8px 14px; text-decoration: none; font-size: 13px; }}
  .empty {{ background: #fff; border: 1px dashed #ccc; border-radius: 12px; padding: 24px; color: #666; }}
  a {{ color: #4338ca; }}
</style>
</head>
<body>
  <h1>HelloWork — file du jour</h1>
  <p class="sub">{len(rows)} candidature(s) à vérifier. Ouvrez chaque offre, relisez, envoyez sur HelloWork,
  puis revenez ici et lancez <code>confirm</code>. Aucun envoi n'est fait par le script.</p>
  {body}
</body>
</html>
"""
