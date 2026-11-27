"""Suivi local des missions commerciales, indépendant du carnet de prospection."""
from __future__ import annotations
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import sqlite3
from private_storage import ensure_private_directory, protect_private_file

DB = Path(__file__).resolve().parent / 'data' / 'client-work.db'
STATES = {'prospect', 'echange', 'devis', 'accepte', 'en_cours', 'livre', 'paye', 'perdu'}
FIELDS = ('nom', 'statut', 'prochaine_action', 'date_action', 'montant', 'notes')

def connection():
    ensure_private_directory(DB.parent)
    if DB.is_symlink():
        raise ValueError('Base client-work symbolique interdite')
    conn = sqlite3.connect(DB, timeout=10)
    protect_private_file(DB)
    protect_private_file(Path(f'{DB}-wal'))
    protect_private_file(Path(f'{DB}-shm'))
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS missions (id INTEGER PRIMARY KEY, nom TEXT NOT NULL, statut TEXT NOT NULL, prochaine_action TEXT NOT NULL, date_action TEXT NOT NULL, montant TEXT NOT NULL, notes TEXT NOT NULL, updated_at TEXT NOT NULL)')
    conn.execute("CREATE TABLE IF NOT EXISTS mission_events (id INTEGER PRIMARY KEY, mission_id INTEGER NOT NULL, statut TEXT NOT NULL, prochaine_action TEXT NOT NULL, date_action TEXT NOT NULL, montant TEXT NOT NULL, at TEXT NOT NULL)")
    DB.chmod(0o600)
    return conn

def list_missions():
    with closing(connection()) as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM missions ORDER BY CASE WHEN date_action = "" THEN 1 ELSE 0 END, date_action, id DESC')]

def save(data):
    if not isinstance(data, dict): raise ValueError('Données invalides')
    values = {}
    for key in FIELDS:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > (2000 if key == 'notes' else 300): raise ValueError('Champ invalide : ' + key)
        values[key] = value.strip()
    if not values['nom'] or values['statut'] not in STATES: raise ValueError('Nom ou statut invalide')
    if values['date_action']:
        try: date.fromisoformat(values['date_action'])
        except ValueError: raise ValueError('Date invalide') from None
    if values['montant']:
        from decimal import Decimal, InvalidOperation
        try:
            amount = Decimal(values['montant'])
            if not amount.is_finite() or amount < 0 or amount > 1000000: raise ValueError('Montant invalide')
        except InvalidOperation: raise ValueError('Montant invalide') from None
    ident = data.get('id')
    if ident is not None and (isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0): raise ValueError('Identifiant invalide')
    with closing(connection()) as conn, conn:
        params = [values[k] for k in FIELDS] + [datetime.now().astimezone().isoformat(timespec='seconds')]
        if ident:
            cursor = conn.execute('UPDATE missions SET nom=?, statut=?, prochaine_action=?, date_action=?, montant=?, notes=?, updated_at=? WHERE id=?', params + [ident])
            if not cursor.rowcount: raise ValueError('Mission introuvable')
        else:
            ident = conn.execute('INSERT INTO missions (nom, statut, prochaine_action, date_action, montant, notes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)', params).lastrowid
        conn.execute("INSERT INTO mission_events (mission_id, statut, prochaine_action, date_action, montant, at) VALUES (?, ?, ?, ?, ?, ?)", (ident, values["statut"], values["prochaine_action"], values["date_action"], values["montant"], params[-1]))
    return ident
