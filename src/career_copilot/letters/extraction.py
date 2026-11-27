"""Offer section parsing, mission extraction, and student job task detection."""

from __future__ import annotations

import re

from career_copilot.letters.text_utils import NOISE, fold, french, has_word, join_fr, lower_first


def mission_sentence(missions: list[str]) -> str:
    if not missions:
        return (
            "J’aborderai le sujet avec méthode : cadrage clair, exécution soignée, "
            "suivi des résultats et documentation réutilisable par l’équipe."
        )
    return (
        f"Concrètement, je souhaite m’investir sur les étapes que vous décrivez : {join_fr(missions)}. "
        "Je les traiterai dans l’ordre, avec des livrables suivis et une documentation claire."
    )


def marketing(text: str) -> bool:
    folded = fold(text)
    return any(
        word in folded
        for word in (
            "collaborateur",
            "millions de clients",
            "reseau de",
            "réseau de",
            "happy trainees",
            "recommandent",
            "acteur majeur",
            "a propos de",
            "à propos de",
            "filiale d",
            "joint-venture",
            "ouvrir nos portes",
            "toutes les competences",
            "toutes les énergies",
            "toutes les energies",
            "nos portes a toutes",
            "banques a l'international",
            "banques à l'international",
        )
    )


def bad_sentence(text: str) -> bool:
    folded = fold(text)
    if text.strip().endswith((":", ":.")):
        return True
    if "activites suivantes" in folded or "activités suivantes" in folded:
        return True
    return any(
        word in folded
        for word in (
            "candidature sera",
            "business partner",
            "tuteur",
            "processus de selection",
            "job description",
            "prochaines etapes",
            "ce stage est fait pour vous",
            "vous serez amene",
            "vous serez amené",
            "realiser les activites",
            "réaliser les activités",
        )
    )


def first_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    match = re.search(r"^(.{40,240}?[.!?])(?:\s|$)", cleaned)
    sentence = match.group(1) if match else cleaned[:220]
    if len(sentence) > 240:
        sentence = sentence[:240].rsplit(" ", 1)[0]
    return sentence.strip()


def objective(lines_list: list[str]) -> str:
    for line in lines_list:
        folded = fold(line)
        if len(line) < 60 or marketing(folded) or bad_sentence(line):
            continue
        if any(
            word in folded
            for word in (
                "ce stage est",
                "ce stage a pour",
                "l'objectif de ce stage",
                "l’objectif de ce stage",
                "l'objectif du stage",
                "l’objectif du stage",
            )
        ):
            sentence = first_sentence(line)
            if not bad_sentence(sentence) and not marketing(sentence):
                return sentence
        if any(
            word in folded
            for word in (
                "vous interviendrez",
                "vous aurez pour mission",
                "vous developperez",
                "vous développerez",
            )
        ):
            sentence = first_sentence(line)
            if (
                not bad_sentence(sentence)
                and not marketing(sentence)
                and not sentence.rstrip().endswith(":")
            ):
                return sentence
        if (
            "vous serez" in folded
            and "activites suivantes" not in folded
            and "activités suivantes" not in folded
        ):
            sentence = first_sentence(line)
            if (
                len(sentence) > 70
                and not sentence.rstrip().endswith(":")
                and not bad_sentence(sentence)
                and not marketing(sentence)
            ):
                return sentence
    return ""


def restate(goal: str) -> str:
    goal = goal.strip().rstrip(".")
    replacements = (
        (r"^l['’]objectif de ce stage est d['’]", "Il s’agit d’"),
        (r"^l['’]objectif du stage est d['’]", "Il s’agit d’"),
        (r"^vous serez amene(?:e|\(e\))?[ée]?\s*a\s+", "La mission demande de "),
        (r"^vous serez amen[ée](?:\(e\))?\s+a\s+", "La mission demande de "),
        (r"^vous développerez ", "La mission demande de développer "),
        (r"^vous developperez ", "La mission demande de développer "),
        (r"^vous interviendrez\s+(?:sur|dans)\s+", "La mission porte sur "),
        (r"\s+a realiser les activites suivantes\s*:?\s*$", ""),
        (r"\s+à réaliser les activités suivantes\s*:?\s*$", ""),
    )
    for pattern, repl in replacements:
        goal = re.sub(pattern, repl, goal, flags=re.IGNORECASE)
    return goal.strip(" :.")


def usable_goal(raw: str) -> str:
    goal = french(restate(raw or ""))
    if not goal:
        return ""
    if not goal.endswith("."):
        goal += "."
    if bad_sentence(goal) or marketing(goal) or goal.rstrip(".").endswith(":") or len(goal) < 55:
        return ""
    return goal[0].upper() + goal[1:]


def bad_mission(text: str) -> bool:
    folded = fold(text)
    if len(text) < 8 or len(text.split()) > 18 or "?" in folded:
        return True
    return any(
        word in folded
        for word in (
            "activites suivantes",
            "activités suivantes",
            "strategique pour",
            "stratégique pour",
            "concernes",
            "concernés",
            "stagiaire contribuera",
            "participation aux reunions",
            "participation aux réunions",
            "ce stage est fait",
            "qui sommes-nous",
            "notre agence",
            "rejoindre ",
            "rejoins ",
            "aventure",
            "notre ambition",
            "nos valeurs",
            "notre culture",
            "signataire",
            "charte d'engagement",
            "bonne nouvelle",
            "let's tech",
            "pourquoi nous",
            "ce que nous offrons",
            "concrètement, tu seras",
            "concrètement, vous serez",
            "tu seras amene",
            "tu seras amené",
            "ton objectif",
            "tes missions",
            "vos missions seront",
            "et si ",
        )
    )


def heading(line: str) -> bool:
    stripped = (line or "").strip()
    return 0 < len(stripped) <= 70 and len(stripped.split()) <= 6 and not stripped.endswith(".")


def section(lines_list: list[str], starts: tuple[str, ...], ends: tuple[str, ...]) -> list[str]:
    start = None
    for index, line in enumerate(lines_list):
        folded = fold(line)
        if heading(line) and any(folded.startswith(word) or word in folded for word in starts):
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines_list)
    for index in range(start, len(lines_list)):
        folded = fold(lines_list[index])
        if heading(lines_list[index]) and any(
            folded.startswith(word) or word == folded for word in ends
        ):
            end = index
            break
    return lines_list[start:end]


def lines(text: str) -> list[str]:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    rows: list[str] = []
    for raw in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t•|-")
        if not line or len(line) < 2:
            continue
        folded = fold(line)
        if any(noise in folded for noise in NOISE):
            continue
        rows.append(line)
    return rows


def missions(lines_list: list[str]) -> list[str]:
    block = section(
        lines_list,
        ("vos missions", "missions", "votre mission"),
        ("votre profil", "profil", "avantage", "livrable", "postuler", "competence"),
    )
    found: list[str] = []
    for index, line in enumerate(block):
        if ":" in line:
            label = line.split(":", 1)[0].strip(" -•–")
            if 8 <= len(label) <= 70 and not bad_mission(label):
                found.append(lower_first(label))
                continue
        if len(line) <= 72 and index + 1 < len(block) and len(block[index + 1]) > len(line):
            label = line.strip(" -•–")
            if not bad_mission(label):
                found.append(lower_first(label))
    unique: list[str] = []
    for item in found:
        cleaned = item.replace(" & ", " et ").strip()
        if cleaned and cleaned not in unique and not bad_mission(cleaned):
            unique.append(cleaned)
    chosen = unique[:3]
    for item in unique[3:]:
        if has_word(item, "poc") or "develop" in fold(item):
            chosen.append(item)
            break
    else:
        if len(unique) > 3:
            chosen.append(unique[3])
    return chosen[:4]


def job_tasks(source: str) -> list[str]:
    folded = fold(source)
    catalog = (
        ("caisse", "la caisse"),
        ("encaissement", "l’encaissement"),
        ("mise en rayon", "la mise en rayon"),
        ("rayon", "le rayon"),
        ("inventaire", "les inventaires"),
        ("service en salle", "le service en salle"),
        ("plonge", "la plonge"),
        ("preparation de commandes", "la préparation de commandes"),
        ("preparateur", "la préparation de commandes"),
        ("manutention", "la manutention et le stockage"),
        ("logistique", "la logistique d’entrepôt"),
        ("trieur", "le tri de colis"),
        ("tri ", "le tri de colis"),
        ("conditionnement", "le conditionnement des colis"),
        ("renfort", "le renfort d’équipe en magasin"),
    )
    found: list[str] = []
    for needle, label in catalog:
        if (
            needle in folded
            and label not in found
            and not (needle == "rayon" and "la mise en rayon" in found)
        ):
            found.append(label)
        if len(found) == 3:
            break
    return found


def notes(lines_list: list[str], mission_items: list[str] | None = None) -> str:
    resolved = mission_items or missions(lines_list)
    if not resolved:
        return ""
    return "Points retenus de l’annonce : " + " ; ".join(resolved) + "."
