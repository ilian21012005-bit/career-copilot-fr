"""Recherche limitée des stages publics PASS ; candidatures sur le site."""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.robotparser
from lxml import html

from filters import _fold
from hellowork import geo
import public_network

BASE = 'https://www.pass.fonction-publique.gouv.fr'
AGENT = 'Job-Etudiant/1.0'
TERMS = ('cybersécurité', 'sécurité informatique', 'réseaux', 'soc',
         'support informatique', 'administration système', 'cloud', 'kubernetes',
         'transformation numérique', 'gestion de projet informatique',
         'analyse de données', 'qualité logicielle')
TITLE_WORDS = ('cyber', 'securite numerique', 'securite informatique', 'systemes et reseaux',
               'administrateur reseau', 'administration reseau', 'detection reseau', 'soc', 'edr', 'siem',
               'pentest', 'anssi', 'dga', 'defense', 'reseaux', 'securite',
               'support informatique', 'support it', 'technicien support', 'support utilisateur',
               'administration systeme', 'administrateur systeme', 'infrastructure',
               'cloud', 'devops', 'kubernetes', 'deploiement informatique',
               'transformation numerique', 'projets si', 'systeme d information',
               'systemes d information', 'cartographie du si',
               'gestion de projet informatique', 'analyse de donnees', 'data analyst',
               'qualite logicielle', 'test logiciel', 'recette applicative', 'observabilite')
DEPARTMENTS = {'essonne':'91', 'hauts-de-seine':'92', 'paris':'75', 'val-de-marne':'94',
               'yvelines':'78', 'val-d-oise':'95', 'seine-saint-denis':'93',
               'seine-et-marne':'77', 'gironde':'33'}
MAX_DETAILS = 30


def _read(url: str) -> bytes:
    status, body, final_url = public_network.fetch(
        url,
        headers={'User-Agent': AGENT, 'Accept': 'text/html'},
        timeout=20,
        max_bytes=2_000_000,
        include_final_url=True,
    )
    final = urllib.parse.urlparse(final_url)
    if final.scheme != 'https' or final.hostname != 'www.pass.fonction-publique.gouv.fr':
        raise ValueError('Redirection PASS hors domaine')
    if status >= 400:
        raise ValueError(f'PASS HTTP {status}')
    return body


def _value(doc, field: str) -> str:
    nodes = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), $cls)]',
                      cls=f' field--name-field-{field} ')
    if not nodes:
        return ''
    node = nodes[0]
    items = node.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " field__item ")]')
    if items:
        return ' '.join(' '.join(x.itertext()).strip() for x in items).strip()
    return ' '.join(node.text_content().split())


def parse(raw: bytes, url: str) -> dict | None:
    doc = html.fromstring(raw)
    title = ' '.join(doc.xpath('//h1[1]//text()')).strip()
    city = _value(doc, 'ville')
    department_name = _fold(_value(doc, 'departement')).replace(' ', '-')
    department = DEPARTMENTS.get(department_name, '')
    if not title or not city:
        return None
    point = geo.geocode(city, department)
    if not point or geo.locate(*point)['status'] != 'in_zone':
        return None
    contract = _value(doc, 'type-de-contrat')
    if 'stage' not in _fold(contract) and 'apprentissage' not in _fold(contract):
        return None
    description = _value(doc, 'description-du-poste')
    profile = _value(doc, 'descriptif-du-profil-reche')
    comments = _value(doc, 'commentaires')
    level = _value(doc, 'niveau-de-diplome-prepare')
    start = _value(doc, 'debut-du-contrat')
    folded_start = _fold(start)
    if re.search(r'\b202[0-5]\b|\b202[8-9]\b|\b20[3-9]\d\b', folded_start):
        return None
    full_title = title if 'stage' in _fold(title) else 'Stage - ' + title
    # PASS affiche parfois une adresse de renseignement et demande le formulaire.
    # Garder toutes ces fiches pour candidature manuelle.
    city_label = f'{city} - {department}' if department else city
    return {
        'id': url, 'url': url, 'email': '', 'title': full_title,
        'name': _value(doc, 'entite') or 'Fonction publique',
        'city': city_label, 'latitude': point[0], 'longitude': point[1],
        'text': f'{full_title} {description} {profile} {level}',
        'description': description, 'source': 'pass', 'contract_type': 'stage',
        'notes': ('Candidature sur le site ; ' + (start or 'dates à confirmer') +
                  (' ; habilitation à vérifier' if 'habilitation' in _fold(description + comments) else '')),
    }


def _select_detail_urls(buckets: list[list[str]], limit: int) -> list[str]:
    if limit <= 0:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for index in range(max((len(bucket) for bucket in buckets), default=0)):
        for bucket in buckets:
            if index < len(bucket) and bucket[index] not in seen:
                seen.add(bucket[index])
                urls.append(bucket[index])
                if len(urls) >= limit:
                    return urls
    return urls


def search() -> list[dict]:
    robot = urllib.robotparser.RobotFileParser()
    robot.parse(_read(BASE + '/robots.txt').decode('utf-8', 'replace').splitlines())
    buckets: list[list[str]] = []
    for term in TERMS:
        params = urllib.parse.urlencode({'combine': term, 'field_type_de_contrat_value[stage]': 'stage',
                                       'items_per_page': '48'})
        url = BASE + '/recherche-offre?' + params
        if not robot.can_fetch(AGENT, url):
            raise RuntimeError('Recherche PASS refusée par robots.txt')
        doc = html.fromstring(_read(url))
        candidates: list[str] = []
        for tr in doc.xpath('//table//tr[td]'):
            links = tr.xpath('.//th//a[starts-with(@href,"/offre/")]')
            if not links:
                continue
            title = _fold(' '.join(links[0].text_content().split()))
            if not any(re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', title)
                       for word in TITLE_WORDS):
                continue
            level = _fold(' '.join(tr.xpath('./td[last()]//text()')))
            import filters as _filters
            if 'niveau 7' in level and 'niveau 6' not in level and not _filters._is_candidate_bac4_plus():
                continue
            target = urllib.parse.urljoin(BASE, links[0].get('href'))
            if target not in candidates and robot.can_fetch(AGENT, target):
                candidates.append(target)
        buckets.append(candidates)
        time.sleep(0.5)
    # Interleave search terms so early cyber results cannot exhaust the detail budget.
    urls = _select_detail_urls(buckets, MAX_DETAILS)
    results = []
    for url in urls:
        try:
            item = parse(_read(url), url)
            if item:
                results.append(item)
        except (OSError, ValueError):
            continue
        finally:
            time.sleep(0.5)
    return results
