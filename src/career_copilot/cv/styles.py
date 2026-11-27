"""CSS templates, lexical constants, and data models for ATS 1-page CVs."""

from __future__ import annotations

from dataclasses import dataclass

CSS = """
    @page { size: A4; margin: 10mm 12mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: Calibri, Arial, Helvetica, sans-serif;
      font-size: 10.15pt; line-height: 1.33; color: #111;
      width: 186mm; margin: 0 auto; padding: 10mm 12mm;
    }
    .sheet { min-height: 277mm; display: flex; flex-direction: column; }
    h1 {
      font-family: Georgia, "Times New Roman", Times, serif;
      font-size: 18.5pt; font-weight: 700; letter-spacing: 0.035em;
      text-align: center; text-transform: uppercase; line-height: 1.12; margin-bottom: 3pt;
    }
    .sub {
      text-align: center; font-size: 9.4pt; line-height: 1.28; margin-bottom: 2pt; color: #222;
    }
    .contact {
      text-align: center; font-size: 9pt; margin-bottom: 9pt; line-height: 1.3;
    }
    .contact a { color: #111; text-decoration: none; }
    h2 {
      font-size: 10pt; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.055em; border-bottom: 1.15px solid #111;
      padding-bottom: 1.5pt; margin: 10pt 0 5.5pt;
    }
    h2:first-of-type { margin-top: 0; }
    .profil { text-align: justify; font-size: 9.75pt; line-height: 1.34; }
    .box {
      font-size: 8.7pt; border: 1px solid #111; padding: 5pt 7pt;
      margin-top: 5pt; line-height: 1.3;
    }
    .row {
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 10pt; margin-top: 6.5pt;
    }
    .row b { font-weight: 700; font-size: 9.8pt; }
    .date { font-size: 8.8pt; white-space: nowrap; color: #222; }
    .role { font-style: italic; margin: 0.5pt 0 1.5pt; font-size: 9.4pt; }
    ul { margin: 0 0 0 14pt; padding: 0; }
    li { margin-bottom: 2pt; font-size: 9.5pt; line-height: 1.3; }
    .skills { font-size: 9.1pt; line-height: 1.34; }
    .skills + .skills { margin-top: 2.5pt; }
    .soft { font-size: 9.2pt; line-height: 1.34; margin-top: 2.5pt; }
    .spacer { flex: 1 1 auto; min-height: 1pt; }
    @media print {
      body { padding: 0; width: auto; }
      a { color: #111; text-decoration: none; }
    }
"""

COMPACT_CSS = """
    body { font-size: 9.15pt !important; line-height: 1.2 !important; padding: 8mm 10mm !important; }
    h1 { font-size: 16.5pt !important; margin-bottom: 2pt !important; }
    h2 { margin: 6pt 0 3pt !important; font-size: 9.2pt !important; }
    .contact { font-size: 8.4pt !important; margin-bottom: 5pt !important; }
    .box { padding: 3.5pt 5pt !important; font-size: 8.2pt !important; }
    li { font-size: 9pt !important; margin-bottom: 1pt !important; }
    .skills, .soft { font-size: 8.5pt !important; }
    .profil { font-size: 9.1pt !important; }
    .spacer { display: none !important; }
"""

MONTHS_SHORT_FR: tuple[str, ...] = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)

ALTERNANCE_TOKENS: tuple[str, ...] = (
    "alternance",
    "apprentissage",
    "contrat pro",
    "professionnalisation",
    "alternant",
    "apprenti",
)

GUARDRAIL_FACT_PREFIXES: tuple[str, ...] = ("ne pas ", "ne jamais ", "interdit")

UPPER_ACRONYMS: frozenset[str] = frozenset(
    {
        "sql",
        "aws",
        "gcp",
        "api",
        "rest",
        "ci/cd",
        "grc",
        "soc",
        "siem",
        "edr",
        "rgpd",
        "nis2",
        "anssi",
        "itil",
        "itsm",
        "glpi",
        "seo",
        "sea",
        "crm",
        "rh",
        "kpi",
        "b2b",
        "btp",
        "cao",
        "bim",
        "plc",
        "scada",
        "vhdl",
        "fpga",
        "pcb",
        "qa",
        "ia",
        "llm",
        "nlp",
        "dbt",
        "etl",
        "hpc",
        "mco",
        "mdm",
        "vpn",
        "vlan",
        "wlan",
        "tcp/ip",
        "html",
        "css",
        "php",
        "c",
        "c#",
        "c++",
    }
)


@dataclass(frozen=True)
class Track:
    """Descriptor for a CV specialization track."""

    key: str
    label: str
    profile: str
    targets: str
