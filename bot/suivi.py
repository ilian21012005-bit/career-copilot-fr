"""Un seul classeur Excel. Les nouvelles annonces s'ajoutent, le suivi saisi reste."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import file_lock
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from config import DATA_DIR, JOB_ALLOW_FULL_TIME, JOB_DISTANCE_KM, ZONES
from filters import FULL_TIME, JOB_MUST, JOB_REJECT, _fold, _km
from jooble import _geocode

SUIVI_PATH = DATA_DIR / "Suivi-candidatures.xlsx"
HEADERS = (
    "Ajouté le",
    "Type",
    "Poste",
    "Entreprise",
    "Ville",
    "km",
    "Contrat / niveau",
    "Lien",
    "Postulé",
    "Statut",
    "Notes",
    "Source",
    "Candidature le",
)
WIDTHS = (14, 16, 46, 28, 32, 8, 22, 54, 12, 16, 28, 16, 16)
VILLEBON = ZONES["job"][0]


def _norm_link(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.netloc:
        return raw
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"se", "v"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(query),
            "",
        )
    )


def _place_key(company: str, title: str, city: str) -> tuple[str, str, str] | None:
    company, title, city = (
        company.casefold().strip(),
        title.casefold().strip(),
        city.casefold().strip(),
    )
    if not company or not title:
        return None
    return (company, title, city)


@contextmanager
def _suivi_lock():
    """Verrou inter-processus pour toutes les lectures/écritures de Suivi-candidatures.xlsx."""
    lock_path = SUIVI_PATH.parent / f".{SUIVI_PATH.name}.lock"
    with file_lock.locked_file(lock_path):
        yield


def _set_cell_text(cell, value) -> None:
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"


def _append_row(sheet: Worksheet, values: list) -> None:
    row = sheet.max_row + 1
    for column, value in enumerate(values, start=1):
        _set_cell_text(sheet.cell(row, column), value)


def _save_book(sheet: Worksheet) -> None:
    SUIVI_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = SUIVI_PATH.with_name(f".{SUIVI_PATH.name}.tmp.{os.getpid()}.xlsx")
    sheet.parent.save(tmp)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, SUIVI_PATH)


def add_many(targets: list[dict]) -> int:
    # Pré-géocodage hors verrou pour ne pas bloquer d'autres processus pendant l'appel réseau.
    precomputed = [(_km_of(target) if target.get("url") else "") for target in targets]
    with _suivi_lock():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sheet = _open()
        known = _known_links(sheet)
        places = _known_places(sheet)
        added = 0
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        for target, km_value in zip(targets, precomputed, strict=True):
            raw_email = (target.get("email") or "").strip()
            link = (target.get("url") or "").strip() or (
                f"mailto:{raw_email}" if raw_email else ""
            )
            normal = _norm_link(link)
            place = _place_key(
                str(target.get("name") or ""),
                str(target.get("title") or ""),
                str(target.get("city") or ""),
            )
            if not link or normal in known or (place and place in places):
                continue
            _ensure_source(sheet)
            camp = str(target.get("campaign") or "")
            is_alt = bool(target.get("alternance")) or camp == "alternance"
            row_type = (
                "Alternance"
                if is_alt
                else ("Stage" if camp == "stage" else "Job étudiant")
            )
            _append_row(
                sheet,
                [
                    today,
                    row_type,
                    target.get("title") or "",
                    target.get("name") or "",
                    target.get("city") or "",
                    km_value,
                    _niveau(target),
                    link,
                    "Non",
                    "À voir",
                    target.get("notes") or "",
                    target.get("source") or "",
                ],
            )
            known.add(normal)
            if place:
                places.add(place)
            added += 1
        _sort(sheet)
        _style(sheet)
        _save_book(sheet)
        return added


def prune_student_jobs() -> tuple[int, int]:
    """Retire les jobs étudiants hors sujet ou à plus de 15 km. Renvoie (gardés, retirés)."""
    with _suivi_lock():
        sheet = _open()
        header = [cell.value for cell in sheet[1]]
        index = {name: position for position, name in enumerate(header)}
        cities = {
            str(row[index["Ville"]] or "")
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if "Ville" in index and index["Ville"] < len(row) and any(row)
        }
    # Géocodage des villes hors verrou fichier.
    distances = {city: _km_of_city(city) for city in cities}

    with _suivi_lock():
        sheet = _open()
        header = [cell.value for cell in sheet[1]]
        index = {name: position for position, name in enumerate(header)}
        kept_jobs = []
        stages = []
        removed = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            record = {
                name: row[position] if position < len(row) else ""
                for name, position in index.items()
            }
            kind = str(record.get("Type") or "")
            city = str(record.get("Ville") or "")
            dist = distances[city] if city in distances else _km_of_city(city)
            if "stage" in _fold(kind):
                record["km"] = dist
                stages.append(record)
                continue
            title = str(record.get("Poste") or "")
            folded = _fold(title)
            applied = _fold(str(record.get("Postulé") or "")) == "oui"
            if applied:
                record["km"] = dist
                kept_jobs.append(record)
                continue
            if any(_fold(word) in folded for word in JOB_REJECT):
                removed += 1
                continue
            if not JOB_ALLOW_FULL_TIME:
                if any(_fold(word) in folded for word in FULL_TIME):
                    removed += 1
                    continue
                if _fold(str(record.get("Contrat / niveau") or "")) == "temps plein":
                    removed += 1
                    continue
            if not any(_fold(word) in folded for word in JOB_MUST):
                removed += 1
                continue
            if dist is None or dist > JOB_DISTANCE_KM:
                removed += 1
                continue
            record["km"] = dist
            kept_jobs.append(record)
        kept_jobs.sort(
            key=lambda item: (
                item.get("km") if isinstance(item.get("km"), (int, float)) else 999
            )
        )
        stages.sort(
            key=lambda item: (
                item.get("km") if isinstance(item.get("km"), (int, float)) else 999
            )
        )
        _rewrite(sheet, kept_jobs + stages)
        return len(kept_jobs), removed


def drop_full_time_jobs(force: bool = False) -> int:
    """Retire les jobs étudiants à temps plein non postulés (sauf en mode blocus/Noël)."""
    if JOB_ALLOW_FULL_TIME and not force:
        return 0
    with _suivi_lock():
        sheet = _open()
        header = [cell.value for cell in sheet[1]]
        index = {name: position for position, name in enumerate(header)}
        kept = []
        removed = 0
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            record = {
                name: row[position] if position < len(row) else ""
                for name, position in index.items()
            }
            kind = _fold(str(record.get("Type") or ""))
            contract = _fold(str(record.get("Contrat / niveau") or ""))
            applied = _fold(str(record.get("Postulé") or ""))
            if "job" in kind and contract == "temps plein" and applied != "oui":
                removed += 1
                continue
            kept.append(record)
        if removed:
            _rewrite(sheet, kept)
        return removed


def _rewrite(sheet: Worksheet, records: list[dict]) -> None:
    book = sheet.parent
    book.remove(sheet)
    fresh = book.create_sheet("Suivi", 0)
    fresh.append(list(HEADERS))
    for record in records:
        fresh.append([record.get(name, "") for name in HEADERS])
    _style(fresh)
    _save_book(fresh)


STATUTS = (
    "À voir",
    "Postulé",
    "Transmise",
    "Relancé",
    "Répondu",
    "Entretien",
    "Refus",
    "Ignorée",
)


def source_name(url: str, stored: str = "") -> str:
    saved = (stored or "").strip().lower()
    if saved in (
        "adzuna",
        "jooble",
        "francetravail",
        "lba",
        "pass",
        "wttj",
        "apec",
        "hellowork",
        "smartrecruiters",
        "workday",
        "csp",
        "teamtailor",
        "recruitee",
        "mail-jobteaser",
        "mail-freework",
        "mail-meteojob",
        "mail-studentjob",
        "mail-campuscyber",
    ):
        return saved
    host = (url or "").lower()
    if "teamtailor.com" in host:
        return "teamtailor"
    if "recruitee.com" in host:
        return "recruitee"
    if "jobteaser.com" in host:
        return "mail-jobteaser"
    if "free-work.com" in host:
        return "mail-freework"
    if "meteojob.com" in host:
        return "mail-meteojob"
    if "studentjob." in host:
        return "mail-studentjob"
    if "campuscyber" in host or "campus-cyber" in host:
        return "mail-campuscyber"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return "workday"
    if (
        "choisirleservicepublic.gouv.fr" in host
        or "place-ep-recrute.talent-soft.com" in host
    ):
        return "csp"
    if "welcometothejungle" in host or "wttj" in host:
        return "wttj"
    if "apec.fr" in host or "apec" in host:
        return "apec"
    if "hellowork" in host:
        return "hellowork"
    if "adzuna" in host:
        return "adzuna"
    if "jooble" in host:
        return "jooble"
    if "pass.fonction-publique.gouv.fr" in host:
        return "pass"
    if (
        "labonnealternance.apprentissage.beta.gouv.fr" in host
        or "apprentissage.beta.gouv.fr" in host
    ):
        return "lba"
    if "francetravail" in host or "pole-emploi" in host or "poleemploi" in host:
        return "francetravail"
    return "autre"


def _ensure_source(sheet: Worksheet) -> None:
    headers = [cell.value for cell in sheet[1]]
    if "Source" in headers:
        return
    sheet.cell(1, len([value for value in headers if value]) + 1).value = "Source"


def _application_date_column(sheet: Worksheet) -> int:
    for cell in sheet[1]:
        if cell.value == "Candidature le":
            return cell.column
    column = sheet.max_column + 1
    sheet.cell(1, column).value = "Candidature le"
    return column


def list_rows() -> list[dict]:
    with _suivi_lock():
        if not SUIVI_PATH.exists():
            return []
        sheet = _open()
        header = [cell.value for cell in sheet[1]]
        index = {name: position for position, name in enumerate(header)}

        def cell(row: tuple, name: str):
            position = index.get(name)
            if position is None or position >= len(row) or row[position] is None:
                return ""
            return row[position]

        rows = []
        for raw in sheet.iter_rows(min_row=2, values_only=True):
            if not any(raw):
                continue
            distance = cell(raw, "km")
            rows.append(
                {
                    "date": str(cell(raw, "Ajouté le")),
                    "applied_date": str(cell(raw, "Candidature le")),
                    "type": str(cell(raw, "Type")),
                    "title": str(cell(raw, "Poste")),
                    "company": str(cell(raw, "Entreprise")),
                    "city": str(cell(raw, "Ville")),
                    "km": distance if isinstance(distance, (int, float)) else None,
                    "contract": str(cell(raw, "Contrat / niveau")),
                    "url": str(cell(raw, "Lien")),
                    "email": str(cell(raw, "Email")),
                    "applied": str(cell(raw, "Postulé") or "Non"),
                    "status": str(cell(raw, "Statut") or "À voir"),
                    "notes": str(cell(raw, "Notes")),
                    "source": source_name(
                        str(cell(raw, "Lien")), str(cell(raw, "Source"))
                    ),
                }
            )
    rows.sort(
        key=lambda item: (
            0 if "job" in _fold(item["type"]) else 1,
            item["km"] if item["km"] is not None else 999,
        )
    )
    return rows


def _declaration_column(sheet: Worksheet, *, create: bool = False) -> int | None:
    for cell in sheet[1]:
        if cell.value == "Déclaration manuelle":
            return cell.column
    if create:
        column = sheet.max_column + 1
        sheet.cell(1, column).value = "Déclaration manuelle"
        return column
    return None


def update_row(
    url: str,
    applied: str | None = None,
    status: str | None = None,
    *,
    applied_at: str = "",
    preserve_progress: bool = False,
    declaration: bool | None = None,
) -> bool:
    with _suivi_lock():
        sheet = _open()
        link_col = _header_index(sheet, "Lien")
        applied_col = _header_index(sheet, "Postulé")
        status_col = _header_index(sheet, "Statut")
        target_norm = _norm_link(url)
        if not target_norm:
            return False
        for row in range(2, sheet.max_row + 1):
            current = str(sheet.cell(row, link_col).value or "").strip()
            if current != url.strip() and (
                not target_norm or _norm_link(current) != target_norm
            ):
                continue
            current_status = sheet.cell(row, status_col).value
            marker_col = _declaration_column(sheet, create=declaration is True)
            marker = sheet.cell(row, marker_col) if marker_col is not None else None
            if declaration is not None:
                if declaration and (
                    current_status not in ("À voir", "Ignorée", None, "Postulé")
                    or (
                        sheet.cell(row, applied_col).value == "Oui"
                        and (marker is None or marker.value != 1)
                    )
                ):
                    return False
                if not declaration and (
                    marker is None or marker.value != 1 or current_status != "Postulé"
                ):
                    return False
            changed = False
            if applied in ("Oui", "Non"):
                sheet.cell(row, applied_col).value = applied
                if marker is not None:
                    marker.value = 1 if declaration is True else None
                _ensure_source(sheet)
                date_cell = sheet.cell(row, _application_date_column(sheet))
                if applied == "Non":
                    date_cell.value = None
                elif not date_cell.value or applied_at:
                    date_cell.value = (
                        applied_at or datetime.now().astimezone().isoformat()
                    )[:10]
                changed = True
            if status in STATUTS and (
                not preserve_progress
                or current_status
                not in ("Transmise", "Relancé", "Répondu", "Entretien", "Refus")
            ):
                sheet.cell(row, status_col).value = status
                changed = True
            if not changed:
                return False
            _save_book(sheet)
            return True
        return False


def record_application(
    url: str,
    *,
    campaign: str,
    title: str,
    company: str,
    city: str,
    source: str,
    notes: str = "",
    contract_type: str = "",
    applied_at: str = "",
    lookup_distance: bool = True,
) -> None:
    """Enregistre ou met à jour une candidature envoyée dans Suivi-candidatures.xlsx."""
    if not url:
        return
    if update_row(
        url,
        applied="Oui",
        status="Postulé",
        applied_at=applied_at,
        preserve_progress=True,
    ):
        return
    target = {
        "url": url,
        "campaign": campaign,
        "title": title,
        "name": company,
        "city": city,
        "source": source,
        "notes": notes,
        "contract_type": contract_type,
    }
    km_value = _km_of(target) if lookup_distance else ""
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    with _suivi_lock():
        sheet = _open()
        _ensure_source(sheet)
        date_col = _application_date_column(sheet)
        normal = _norm_link(url)
        if normal in _known_links(sheet):
            link_col = _header_index(sheet, "Lien")
            applied_col = _header_index(sheet, "Postulé")
            status_col = _header_index(sheet, "Statut")
            for row in range(2, sheet.max_row + 1):
                cur = str(sheet.cell(row, link_col).value or "").strip()
                if cur == url.strip() or _norm_link(cur) == normal:
                    sheet.cell(row, applied_col).value = "Oui"
                    marker_col = _declaration_column(sheet)
                    if marker_col is not None:
                        sheet.cell(row, marker_col).value = None
                    if sheet.cell(row, status_col).value in ("À voir", "Ignorée", None):
                        sheet.cell(row, status_col).value = "Postulé"
                    if not sheet.cell(row, date_col).value or applied_at:
                        sheet.cell(row, date_col).value = (applied_at or today)[:10]
                    _save_book(sheet)
                    return
        _append_row(
            sheet,
            [
                today,
                "Stage" if campaign == "stage" else "Job étudiant",
                title,
                company,
                city,
                km_value,
                _niveau(target),
                url,
                "Oui",
                "Postulé",
                notes,
                source,
            ],
        )
        sheet.cell(sheet.max_row, date_col).value = (applied_at or today)[:10]
        _sort(sheet)
        _style(sheet)
        _save_book(sheet)


def mark_ignored_many(urls: set[str]) -> int:
    """Marque en une seule écriture toutes les URLs données comme Ignorée."""
    clean = {str(u or "").strip() for u in urls if str(u or "").strip()}
    if not clean:
        return 0
    with _suivi_lock():
        if not SUIVI_PATH.exists():
            return 0
        sheet = _open()
        link_col = _header_index(sheet, "Lien")
        applied_col = _header_index(sheet, "Postulé")
        status_col = _header_index(sheet, "Statut")
        updated = 0
        for row in range(2, sheet.max_row + 1):
            current = str(sheet.cell(row, link_col).value or "").strip()
            if current not in clean:
                continue
            status = str(sheet.cell(row, status_col).value or "").strip()
            applied = str(sheet.cell(row, applied_col).value or "").strip().casefold()
            if applied == "oui" or status not in {
                "",
                "À voir",
                "A voir",
                "À postuler",
                "Préparée",
                "Nouveau",
            }:
                continue
            sheet.cell(row, applied_col).value = "Non"
            sheet.cell(row, status_col).value = "Ignorée"
            updated += 1
        if updated:
            _save_book(sheet)
        return updated


def delete_row(url: str) -> bool:
    with _suivi_lock():
        sheet = _open()
        link_col = _header_index(sheet, "Lien")
        for row in range(2, sheet.max_row + 1):
            current = str(sheet.cell(row, link_col).value or "").strip()
            if current != url.strip():
                continue
            sheet.delete_rows(row, 1)
            _save_book(sheet)
            return True
        return False


def _open() -> Worksheet:
    if SUIVI_PATH.exists():
        book = load_workbook(SUIVI_PATH)
        return book.active
    book = Workbook()
    sheet = book.active
    sheet.title = "Suivi"
    sheet.append(list(HEADERS))
    return sheet


def _known_links(sheet: Worksheet) -> set[str]:
    column = _header_index(sheet, "Lien")
    found = set()
    for row in sheet.iter_rows(
        min_row=2, min_col=column, max_col=column, values_only=True
    ):
        if row[0]:
            found.add(_norm_link(str(row[0])))
    return found


def _known_places(sheet: Worksheet) -> set[tuple[str, str, str]]:
    header = [cell.value for cell in sheet[1]]
    index = {name: position for position, name in enumerate(header)}
    found: set[tuple[str, str, str]] = set()
    needed = ("Entreprise", "Poste", "Ville")
    if any(name not in index for name in needed):
        return found
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        values = [row[index[name]] if index[name] < len(row) else "" for name in needed]
        place = _place_key(*(str(value or "") for value in values))
        if place:
            found.add(place)
    return found


def _header_index(sheet: Worksheet, name: str) -> int:
    for cell in sheet[1]:
        if cell.value == name:
            return cell.column
    raise KeyError(name)


def _km_of(target: dict) -> float | str:
    lat = target.get("latitude")
    lon = target.get("longitude")
    origin_lat = target.get("origin_lat")
    origin_lon = target.get("origin_lon")
    if None in (lat, lon, origin_lat, origin_lon):
        return _km_of_city(str(target.get("city") or "")) or ""
    return round(_km(origin_lat, origin_lon, lat, lon), 1)


def _km_of_city(city: str) -> float | None:
    lowered = city.lower()
    if "arrondissement" in lowered or lowered.startswith("paris"):
        place = "Paris"
    else:
        place = city.split(",")[0].strip()
    lat, lon = _geocode(place or city)
    if lat is None or lon is None:
        return None
    return round(_km(VILLEBON["lat"], VILLEBON["lon"], lat, lon), 1)


def _niveau(target: dict) -> str:
    title = (target.get("title") or "").lower()
    contract = (target.get("contract_type") or "").lower()
    if "stage" in title:
        return "Stage"
    if contract in ("part_time", "part-time"):
        return "Temps partiel"
    if contract in ("full_time", "permanent"):
        return "Temps plein"
    if "cdd" in title:
        return "CDD"
    if "cdi" in title:
        return "CDI"
    if "h" in title and any(
        mark in title for mark in ("15h", "20h", "25h", "30h", "35h")
    ):
        return "Horaires dans le titre"
    return "Non précisé"


def _sort(sheet: Worksheet) -> None:
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    if not rows:
        return

    def rank(row: tuple) -> tuple:
        kind = _fold(str(row[1] or ""))
        distance = row[5]
        number = distance if isinstance(distance, (int, float)) else 999
        return (0 if "job" in kind else 1, number)

    rows.sort(key=rank)
    link_column = _header_index(sheet, "Lien")
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row, link_column).hyperlink = None
    for offset, values in enumerate(rows, start=2):
        for column, value in enumerate(values, start=1):
            _set_cell_text(sheet.cell(offset, column), value)


def _style(sheet: Worksheet) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
    for index, width in enumerate(WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    link_column = _header_index(sheet, "Lien") - 1
    for row in sheet.iter_rows(min_row=2, max_col=len(HEADERS)):
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        link = row[link_column]
        if link.value:
            link.hyperlink = str(link.value)
            link.font = Font(color="0563C1", underline="single")
        else:
            link.hyperlink = None
    last = max(sheet.max_row, 2)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{last}"
    sheet.freeze_panes = "A2"
    _validations(sheet, last)
    sheet.row_dimensions[1].height = 22
    sheet.sheet_view.showGridLines = False


def _validations(sheet: Worksheet, last: int) -> None:
    sheet.data_validations.dataValidation.clear()
    postule_col = get_column_letter(_header_index(sheet, "Postulé"))
    statut_col = get_column_letter(_header_index(sheet, "Statut"))
    postule = DataValidation(type="list", formula1='"Non,Oui"', allow_blank=False)
    statut = DataValidation(
        type="list",
        formula1='"' + ",".join(STATUTS) + '"',
        allow_blank=False,
    )
    postule.error = "Choisis Oui ou Non"
    statut.error = "Choisis un statut"
    postule.errorTitle = "Postulé"
    statut.errorTitle = "Statut"
    sheet.add_data_validation(postule)
    sheet.add_data_validation(statut)
    postule.add(f"{postule_col}2:{postule_col}{max(last, 200)}")
    statut.add(f"{statut_col}2:{statut_col}{max(last, 200)}")
