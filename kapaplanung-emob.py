"""Eigenstaendige Wochenplanung /kapa-emob: Vormontage nach Starttermin, Endmontage nach Endtermin.

Keine Importe aus kapaplanung.py. Keine projektbedingten Terminverschiebungen.
Direkte Registrierung mit @app.route beim Import im Flask-App-Start.
"""
from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import time
import threading
import re

import pyodbc
from flask import current_app, jsonify, render_template, request, session
from config import connectionString
from model import app, db, AuftragInfo, Personal, StundenKW

MACHINE_GROUPS = {
    '2440-18': 'Montage HAK',
    '2440-17': 'Montage Anschlussmodul',
    '2440-14': 'Endmontage Linie'
}
TEAM = 'E-Mobility'
TEAMLEITER_FILE = Path(__file__).with_name('teamleiter_kapa.json')
EMOB_DEBUG = True  # Nach dem Debuggen auf False setzen.


class EmobPackingStatus(db.Model):
    """Separater, dauerhaft gespeicherter Verpackungsstatus je Fertigungsauftrag."""

    __tablename__ = 'kapa_emob_verpackt'

    fa_nr = db.Column(db.String(100), primary_key=True)
    verpackt = db.Column(db.Boolean, nullable=False, default=False)


_EMOB_PACKING_TABLE_READY = False
_EMOB_PACKING_TABLE_LOCK = threading.Lock()


def _ensure_emob_packing_table():
    """Legt nur die neue Status-Tabelle bei Bedarf an (keine ERP-Tabellen)."""
    global _EMOB_PACKING_TABLE_READY
    if _EMOB_PACKING_TABLE_READY:
        return
    with _EMOB_PACKING_TABLE_LOCK:
        if not _EMOB_PACKING_TABLE_READY:
            EmobPackingStatus.__table__.create(bind=db.engine, checkfirst=True)
            _EMOB_PACKING_TABLE_READY = True


def _get_emob_packing_states():
    """Liest alle manuell gepflegten Verpackt-Haken gesammelt aus der App-DB."""
    _ensure_emob_packing_table()
    return {
        _text(row.fa_nr): bool(row.verpackt)
        for row in EmobPackingStatus.query.all()
    }


def _debug_emob(message):
    """Schreibt begrenzte E-Mob-Diagnosen ins Flask-Konsolenfenster."""
    if EMOB_DEBUG:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[KAPA-EMOB DEBUG {timestamp}] {message}', flush=True)


def _text(value):
    return '' if value is None else str(value).strip()


def _fa_key(value):
    """Normalisiert FA-Schlüssel für DB-Werte wie 3145117, 3145117.0 oder Leerzeichen."""
    text = _text(value)
    if not text:
        return ''
    compact = text.replace(' ', '')
    if re.fullmatch(r'[-+]?\d+\.0+', compact):
        return compact.split('.', 1)[0]
    return text


def _get_erp_completion_status(order):
    """Liest die beiden Voraussetzungen direkt aus den ERP-Arbeitsgängen."""
    conn = pyodbc.connect(connectionString)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                MAX(CASE WHEN PmNr = '2440-14' AND Zustand = 60 THEN 1 ELSE 0 END),
                MAX(CASE WHEN PmNr = '2450-11' AND Zustand = 60 THEN 1 ELSE 0 END)
            FROM INFRADB.dbo.FAPOS WITH (NOLOCK)
            WHERE Typ = 'A'
              AND PmNr IN ('2440-14', '2450-11')
              AND LTRIM(RTRIM(CONVERT(nvarchar(100), Auftrag))) = ?
        """, (_fa_key(order),))
        row = cursor.fetchone()
        return bool(row and row[0] == 1), bool(row and row[1] == 1)
    finally:
        conn.close()


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _value(record, *names):
    for name in names:
        value = record.get(name) if isinstance(record, dict) else getattr(record, name, None)
        if value is not None:
            return value
    return None


def _is_emob(value):
    return _text(value).casefold() in ('e-mobility', 'e mobility')


def _weekly_hours(record):
    minutes = _value(record, 'Minuten', 'Produktionsminuten')
    if minutes is not None:
        return _number(minutes) / 60
    hours = _value(record, 'Stunden', 'StundenKW', 'Sollstunden', 'Wochenstunden',
                   'Arbeitsstunden', 'Hours', 'Kapazitaet', 'Kapazität', 'Std')
    return _number(hours) if hours is not None else None


def _person_key(record):
    return _text(_value(record, 'PersNr', 'PersonalNr', 'MitarbeiterNr', 'MitarbeiterID',
                        'PersonalID', 'PersonalId', 'person_id', 'id'))


def _week_key(record):
    year = _value(record, 'Jahr', 'jahr', 'Year', 'year', 'Kalenderjahr')
    week = _value(record, 'KW', 'Kw', 'kw', 'Kalenderwoche', 'Woche', 'week')
    if year is not None and week is not None:
        try:
            return int(year), int(week)
        except (ValueError, TypeError):
            pass
    value = _value(record, 'Datum', 'datum', 'Date', 'date', 'Tag')
    if hasattr(value, 'isocalendar'):
        iso = value.isocalendar()
        return int(iso[0]), int(iso[1])
    return None


def get_emob_capacity(week_keys):
    """Liest bestehende Teamkapazitaet ohne Aenderung der Quelldaten."""
    capacity = {key: None for key in week_keys}
    if TEAMLEITER_FILE.exists():
        try:
            data = json.loads(TEAMLEITER_FILE.read_text(encoding='utf-8'))
            rate = min(max(_number(data.get('settings', {}).get('absence_rate'), .10), 0), 1)
            employees = [employee for employee in data.get('employees', [])
                         if employee.get('active', True) and _is_emob(employee.get('team'))]
            for year, week in week_keys:
                total = 0.0
                attendance = data.get('attendance', {}).get(f'{year}-KW-{week:02d}', {})
                for employee in employees:
                    hours = max(0, _number(employee.get('weekly_hours')))
                    entry = attendance.get(str(employee.get('id')), {})
                    status = _text(entry.get('status')).casefold()
                    if status == 'anwesend':
                        worked = _number(entry.get('hours'), hours)
                    elif status in ('urlaub', 'krank'):
                        worked = _number(entry.get('hours'), 0)
                    elif status in ('schulung', 'sonstiges'):
                        worked = 0
                    else:
                        worked = hours
                    total += min(max(worked, 0), hours) * (1 - rate)
                capacity[(year, week)] = total
            return capacity
        except (OSError, ValueError, TypeError, AttributeError):
            current_app.logger.warning('E-Mob-Kapazitaetsdatei konnte nicht gelesen werden.', exc_info=True)
            # Beschaedigte fuehrende Quelle nicht durch scheinbar valide Werte ersetzen.
            return capacity
    try:
        people = Personal.query.all()
        rows = StundenKW.query.all()
    except Exception:
        current_app.logger.warning('Optionale E-Mob-Kapazitaetstabellen nicht verfuegbar.', exc_info=True)
        return capacity
    person_teams = {}
    default_hours = 0.0
    has_default = False
    for person in people:
        team = _value(person, 'Team', 'team', 'Bereich', 'bereich', 'Abteilung', 'abteilung', 'Gruppe', 'gruppe')
        person_teams[_person_key(person)] = team
        if _is_emob(team):
            hours = _weekly_hours(person)
            if hours is not None:
                default_hours += hours
                has_default = True
    if has_default:
        capacity = {key: default_hours for key in week_keys}
    explicit = defaultdict(float)
    for row in rows:
        key = _week_key(row)
        if key not in capacity:
            continue
        team = _value(row, 'Team', 'team', 'Bereich', 'bereich', 'Abteilung', 'abteilung', 'Gruppe', 'gruppe')
        if team is None:
            team = person_teams.get(_person_key(row))
        if team is None:
            related = _value(row, 'Personal', 'personal', 'Mitarbeiter', 'mitarbeiter')
            team = _value(related, 'Team', 'team', 'Bereich', 'bereich', 'Abteilung', 'abteilung', 'Gruppe', 'gruppe')
        hours = _weekly_hours(row)
        if _is_emob(team) and hours is not None:
            explicit[key] += hours
    capacity.update(explicit)
    return capacity


def get_planning_weeks(reference=None, before=6, after=6):
    reference = reference or datetime.now()
    iso = reference.isocalendar()
    monday = datetime.fromisocalendar(int(iso[0]), int(iso[1]), 1)
    keys = []
    for offset in range(-before, after + 1):
        iso = (monday + timedelta(weeks=offset)).isocalendar()
        keys.append((int(iso[0]), int(iso[1])))
    return keys


def get_emob_jobs(gruppe, date_min, date_max, durchlauf=False):
    """Liest passende Montagezeilen und Erzeugnisdaten effizient je FA."""
    placeholders = ', '.join('?' for _ in MACHINE_GROUPS)
    if date_min is None:
        # Rueckstand benoetigt keine abgeschlossenen Status-60-Auftraege.
        iso = datetime.now().isocalendar()
        lower_bound = datetime.fromisocalendar(int(iso[0]), int(iso[1]), 1)
        start_filter = 'AND (FAPOS.StartTermPlan >= ? OR FAPOS.Zustand < 60)'
        start_params = (lower_bound,)
        if durchlauf:
            # Endmontage wird nach Endtermin eingeplant: Zeilen mit Endtermin ab aktueller KW mitladen.
            start_filter = 'AND (FAPOS.StartTermPlan >= ? OR FAPOS.Zustand < 60 OR FAPOS.EndTermPlan >= ?)'
            start_params = (lower_bound, lower_bound)
    else:
        start_filter = 'AND FAPOS.StartTermPlan >= ?'
        start_params = (date_min,)

    sql = f"""
        WITH A_ZEILEN AS (
            SELECT FAPOS.Zustand, FAPOS.Auftrag, FAPOS.Teil, TEILE.Bez,
                   FAPOS.Mng, FAPOS.StartTermPlan, FAPOS.EndTermPlan,
                   FAPOS.Zeit, FAPOS.PmNr
            FROM INFRADB.dbo.FAPOS AS FAPOS WITH (NOLOCK)
            JOIN INFRADB.dbo.TEILE AS TEILE WITH (NOLOCK)
              ON FAPOS.Teil = TEILE.Teil
            WHERE TEILE.Gruppe = ?
              AND FAPOS.Zustand BETWEEN ? AND ?
              AND FAPOS.Typ = 'A'
              AND FAPOS.Stat <> 'Z'
              AND FAPOS.PmNr IN ({placeholders})
              {start_filter}
              AND FAPOS.StartTermPlan < ?
        ),
        ERZEUGNIS AS (
            SELECT E.Auftrag,
                   CASE WHEN COUNT_BIG(*) = 1 THEN MAX(E.MngRest) ELSE NULL END AS Restmenge,
                   COUNT_BIG(*) AS EZeilenAnzahl,
                   CASE WHEN COUNT_BIG(*) = 1 THEN MAX(E.SerienNr) ELSE NULL END AS SerienNr,
                   CASE WHEN COUNT_BIG(*) = 1 THEN MAX(E.SerienNrBis) ELSE NULL END AS SerienNrBis,
                   CASE
                       WHEN COUNT(DISTINCT NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), E.Proj))), N'')) = 1
                       THEN MAX(NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), E.Proj))), N''))
                       ELSE NULL
                   END AS Projektnummer
            FROM INFRADB.dbo.FAPOS AS E WITH (NOLOCK)
            JOIN (SELECT DISTINCT Auftrag FROM A_ZEILEN) AS AUFTRAEGE
              ON AUFTRAEGE.Auftrag = E.Auftrag
            WHERE E.Typ = 'E'
            GROUP BY E.Auftrag
        ),
        FERTIGSTATUS AS (
            SELECT X.Auftrag,
                   MAX(CASE WHEN X.PmNr = '2440-14' AND X.Zustand = 60 THEN 1 ELSE 0 END) AS LinieFertig,
                   MAX(CASE WHEN X.PmNr = '2450-11' AND X.Zustand = 60 THEN 1 ELSE 0 END) AS PruefungFertig
            FROM INFRADB.dbo.FAPOS AS X WITH (NOLOCK)
            JOIN (SELECT DISTINCT Auftrag FROM A_ZEILEN) AS AUFTRAEGE
              ON AUFTRAEGE.Auftrag = X.Auftrag
            WHERE X.Typ = 'A'
              AND X.PmNr IN ('2440-14', '2450-11')
            GROUP BY X.Auftrag
        )
        SELECT A.Zustand, A.Auftrag, A.Teil, A.Bez,
               A.Mng, A.StartTermPlan, A.EndTermPlan,
               A.Zeit, A.PmNr,
               COALESCE(E.Projektnummer, N'') AS Projektnummer,
               E.Restmenge,
               COALESCE(E.EZeilenAnzahl, 0) AS EZeilenAnzahl,
               E.SerienNr,
               E.SerienNrBis,
               COALESCE(PROJTEXT.Projektbezeichnung, N'') AS Projektbezeichnung,
               PROJTEXT.TEXTE1Schluessel AS TEXTE1Schluessel,
               COALESCE(FERTIGSTATUS.LinieFertig, 0) AS LinieFertig,
               COALESCE(FERTIGSTATUS.PruefungFertig, 0) AS PruefungFertig
        FROM A_ZEILEN AS A
        LEFT JOIN ERZEUGNIS AS E ON E.Auftrag = A.Auftrag
        LEFT JOIN FERTIGSTATUS ON FERTIGSTATUS.Auftrag = A.Auftrag
        OUTER APPLY (
            SELECT TOP (1) T.Schluessel AS TEXTE1Schluessel,
                           T.[Text] AS Projektbezeichnung
            FROM INFRADB.dbo.TEXTE1 AS T WITH (NOLOCK)
            WHERE E.Projektnummer IS NOT NULL
              AND T.Schluessel = E.Projektnummer
            ORDER BY T.Schluessel
        ) AS PROJTEXT
    """

    query_started = time.perf_counter()
    _debug_emob(f"SQL-Abfrage startet: Abteilung={gruppe!r}, date_min={date_min!r}, date_max={date_max!r}")
    conn = None
    try:
        conn = pyodbc.connect(connectionString)
        connected_at = time.perf_counter()
        conn.timeout = 60
        cursor = conn.cursor()
        cursor.execute(sql, (gruppe, 20, 60, *MACHINE_GROUPS, *start_params, date_max))
        execute_seconds = time.perf_counter() - connected_at
        connection_seconds = connected_at - query_started
        _debug_emob(
            f"Datenbankverbindung={connection_seconds:.2f} s; SQL execute={execute_seconds:.2f} s; "
            "lese Ergebniszeilen."
        )
        records = cursor.fetchall()
        fetch_seconds = time.perf_counter() - connected_at - execute_seconds
        missing = [row for row in records if len(row) > 14 and not _text(row[14])]
        _debug_emob(
            f"Abfrage fertig: {len(records)} Zeilen; execute={execute_seconds:.2f} s, "
            f"fetch={fetch_seconds:.2f} s; Projektbezeichnung fehlt bei {len(missing)} Zeilen."
        )
        for row in missing[:20]:
            tex_key = row[15] if len(row) > 15 else None
            _debug_emob(
                f"Projekt-Match FA={row[1]!r}, Maschinengruppe={row[8]!r}, "
                f"E.Proj={row[9]!r}, TEXTE1.Schluessel={tex_key!r}, Text={row[14]!r}"
            )
        if len(missing) > 20:
            _debug_emob(f"Weitere {len(missing) - 20} fehlende Projektbezeichnungen nicht ausgegeben.")
        return records
    except Exception as exc:
        _debug_emob(f"SQL-Fehler: {exc!r}")
        raise
    finally:
        if conn is not None:
            conn.close()



# Einplanung der Wochenuebersicht: Vormontage (HAK, Anschlussmodul) nach
# Starttermin, Endmontage nach Endtermin (KW, in der der Endtermin liegt).
ENDMONTAGE_CODE = '2440-14'


def berechne_durchlauf_daten(records):
    """Frueheste Start- und Endtermine je (FA, PmNr) aus den Zeilen."""
    starts, ends = {}, {}
    for record in records:
        order = _fa_key(record[1])
        pmnr = _text(record[8])
        if not order or pmnr not in MACHINE_GROUPS:
            continue
        start, end = record[5], record[6]
        if hasattr(start, 'isocalendar') and ((order, pmnr) not in starts or start < starts[(order, pmnr)]):
            starts[(order, pmnr)] = start
        if hasattr(end, 'isocalendar') and ((order, pmnr) not in ends or end < ends[(order, pmnr)]):
            ends[(order, pmnr)] = end
    return starts, ends


def planungs_datum(pmnr, order, starts, ends):
    """Datum fuer die KW-Zuordnung: Endmontage nach Endtermin, Vormontage nach Starttermin."""
    if pmnr == ENDMONTAGE_CODE:
        return ends[(order, pmnr)]
    return starts[(order, pmnr)]


def build_emob_week_plan(records, auftrag_info, week_keys, capacities=None, reference=None, packing_states=None, durchlauf=False):
    """Rueckstand vor der aktuellen KW, danach Einplanung allein nach Startdatum.

    Mengen je FA/Montagezelle nicht doppelt zaehlen. Proj und Enddatum
    beeinflussen die Einplanung nicht. Vergangene KW werden nicht einzeln gezeigt.
    """
    reference = reference or datetime.now()
    iso = reference.isocalendar()
    current_key = (int(iso[0]), int(iso[1]))
    current_monday = datetime.fromisocalendar(*current_key, 1)
    week_keys = sorted(set(key for key in week_keys if key >= current_key))
    # FA-Nummern sind nicht zwingend als Unique-Key angelegt. Wenn es zu einer
    # FA mehrere AuftragInfo-Zeilen gibt, darf eine leere Zeile eine vorhandene
    # Bemerkung nicht überschreiben.
    info = {}
    for item in auftrag_info:
        key = _fa_key(_value(item, 'fa_nr', 'FANr', 'Auftrag'))
        if not key:
            continue
        comment = _text(_value(item, 'fa_bemerk', 'Bemerkung', 'Kommentar'))
        if comment or key not in info:
            info[key] = comment
    packing_states = packing_states or {}
    durchlauf_starts, durchlauf_ends = berechne_durchlauf_daten(records)
    grouped = defaultdict(dict)
    visible = set(week_keys)
    for index, record in enumerate(records):
        status, order, part, description, quantity, start, end, minutes, pmnr, project = record[:10]
        total_quantity = _number(quantity)
        serial_number = _text(record[12]) if len(record) > 12 else ''
        serial_number_to = _text(record[13]) if len(record) > 13 else ''
        project_description = _text(record[14]) if len(record) > 14 else ''
        line_done = _number(record[16], 0) == 1 if len(record) > 16 else False
        inspection_done = _number(record[17], 0) == 1 if len(record) > 17 else False
        # Die Restmenge stammt ausschliesslich aus der E-Zeile derselben FA.
        # Fehlende/mehrdeutige Erzeugniszeilen niemals als gefertigte Menge ausgeben.
        remaining_quantity = _number(record[10], None) if len(record) > 10 else None
        e_count = _number(record[11], None) if len(record) > 11 else None
        quantity_note = ''
        if e_count == 0:
            quantity_note = 'Keine Erzeugniszeile (Typ E) fuer diese FA gefunden.'
        elif e_count is not None and e_count != 1:
            quantity_note = 'Mehrere Erzeugniszeilen (Typ E): Restmenge nicht eindeutig.'
        elif remaining_quantity is None:
            quantity_note = 'Restmenge der Erzeugniszeile nicht verfuegbar.'
        if quantity_note:
            remaining_quantity = None
        pmnr = _text(pmnr)
        if pmnr not in MACHINE_GROUPS or not hasattr(start, 'isocalendar'):
            continue
        plan_date = start
        if durchlauf:
            plan_date = planungs_datum(pmnr, _fa_key(order), durchlauf_starts, durchlauf_ends)
        iso = plan_date.isocalendar()
        key = (int(iso[0]), int(iso[1]))
        if key < current_key:
            # Status 60 nur im Rueckstand ausblenden, auch aus dessen Summen.
            if _number(status) == 60:
                continue
            key = 'backlog'
        elif key not in visible:
            continue
        order_key = _fa_key(order)
        merge_key = (pmnr, order_key or f'__row_{index}')
        jobs = grouped[key]
        if merge_key not in jobs:
            jobs[merge_key] = {'Auftrag': order, 'Zustand': _text(status), 'Projekt': _text(project),
                              'Teil': _text(part), 'Bez': _text(description), 'Projektbezeichnung': project_description,
                              'Mng': _number(quantity),
                              'MngRest': remaining_quantity,
                              'MngGefertigt': (total_quantity - remaining_quantity
                                               if remaining_quantity is not None else None),
                              'MengenHinweis': quantity_note,
                              'SerienNr': serial_number, 'SerienNrBis': serial_number_to,
                              'Start': start, 'Ende': durchlauf_ends.get((_fa_key(order), pmnr)), 'PmNr': pmnr,
                              'ZeitStunden': _number(minutes) / 60,
                              'LinieFertig': line_done,
                              'PruefungFertig': inspection_done,
                              'Verpackt': bool(packing_states.get(order_key, False)),
                              'Kommentar': info.get(order_key, '')}
        else:
            job = jobs[merge_key]
            job['LinieFertig'] = job['LinieFertig'] or line_done
            job['PruefungFertig'] = job['PruefungFertig'] or inspection_done
            job['ZeitStunden'] += _number(minutes) / 60
            job['Mng'] = max(job['Mng'], _number(quantity))
            # Wiederholte Arbeitsgaenge derselben FA nicht doppelt zaehlen.
            if job['MngRest'] is None or remaining_quantity is None:
                job['MngRest'] = None
                job['MngGefertigt'] = None
                job['MengenHinweis'] = job['MengenHinweis'] or quantity_note
            else:
                job['MngRest'] = min(job['MngRest'], remaining_quantity)
                job['MngGefertigt'] = job['Mng'] - job['MngRest']
            # Bei gemischten Arbeitsgangstatus bleibt der niedrigere sichtbar.
            if _number(status, 999) < _number(job['Zustand'], 999):
                job['Zustand'] = _text(status)
            if start < job['Start']:
                job['Start'] = start
            for field, value in [('Projekt', project), ('Projektbezeichnung', project_description),
                                 ('Teil', part), ('Bez', description),
                                 ('SerienNr', serial_number), ('SerienNrBis', serial_number_to)]:
                text = _text(value)
                if text and text not in job[field].split(', '):
                    job[field] = ', '.join(filter(None, [job[field], text]))
    capacities = capacities or {}

    def make_entry(key, year=None, week=None):
        jobs = list(grouped[key].values())
        blocks = []
        for pmnr, name in MACHINE_GROUPS.items():
            phase_jobs = sorted([job for job in jobs if job['PmNr'] == pmnr],
                                key=lambda job: (job['Start'], _text(job['Auftrag'])))
            blocks.append({'pmnr': pmnr, 'name': name, 'jobs': phase_jobs,
                           'load_hours': sum(job['ZeitStunden'] for job in phase_jobs),
                           'quantity_sum': sum(job['Mng'] for job in phase_jobs),
                           'manufactured_quantity_sum': (
                               None if any(job['MngGefertigt'] is None for job in phase_jobs)
                               else sum(job['MngGefertigt'] for job in phase_jobs)),
                           'order_count': len(phase_jobs)})
        load = sum(block['load_hours'] for block in blocks)
        backlog = key == 'backlog'
        capacity = None if backlog else capacities.get(key)
        if backlog:
            label = 'Rückstand'
            date_range = f'Start vor {current_monday:%d.%m.%Y}'
        else:
            monday = datetime.fromisocalendar(year, week, 1)
            label = f'KW {week:02d}'
            date_range = f'{monday:%d.%m.} - {monday + timedelta(days=6):%d.%m.%Y}'
        return {'year': year, 'week': week, 'label': label, 'date_range': date_range,
                'is_backlog': backlog, 'blocks': blocks, 'jobs': jobs,
                'load_hours': load, 'capacity_hours': capacity,
                'utilisation': load / capacity * 100 if capacity is not None and capacity > 0 else None}

    return [make_entry('backlog')] + [make_entry((year, week), year, week) for year, week in week_keys]


@app.route('/kapa-emob', methods=['GET'])
def kapa_emob_index():
    route_started = time.perf_counter()
    now = datetime.now()
    weeks = get_planning_weeks(now, before=0, after=6)
    date_max = datetime.fromisocalendar(*weeks[-1], 1) + timedelta(weeks=1)
    records = get_emob_jobs(session.get('abteilung', 'M1'), None, date_max, durchlauf=True)
    _debug_emob(f"Rohdaten fuer Wochenplanung geladen: {len(records)} Zeilen nach {time.perf_counter() - route_started:.2f} s.")
    packing_states = _get_emob_packing_states()
    plan = build_emob_week_plan(
        records, AuftragInfo.query.all(), weeks, get_emob_capacity(weeks),
        reference=now, packing_states=packing_states, durchlauf=True
    )
    _debug_emob(f"Wochenplan aufgebaut; rendere Seite. Laufzeit bisher {time.perf_counter() - route_started:.2f} s.")
    page = render_template('kapa_emob.html', week_plan=plan,
                           current_year=int(now.isocalendar()[0]), current_week=int(now.isocalendar()[1]))
    _debug_emob(f"Seite fertig gerendert in {time.perf_counter() - route_started:.2f} s.")
    return page


@app.route('/api/kapa-emob/remark', methods=['POST'])
def update_emob_remark():
    """Separater Endpunkt; verwendet dieselbe zentrale FA-Bemerkungstabelle."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(success=False, error='Ungueltige Eingabe.'), 400
    order = _text(data.get('fa_nr'))
    comment = _text(data.get('comment'))
    if not order:
        return jsonify(success=False, error='Keine FA-Nummer angegeben.'), 400
    if len(comment) > 2000:
        return jsonify(success=False, error='Maximal 2000 Zeichen erlaubt.'), 400

    packaging_supplied = 'verpackt' in data
    packaged = data.get('verpackt')
    if packaging_supplied and not isinstance(packaged, bool):
        return jsonify(success=False, error='Verpackt muss true oder false sein.'), 400

    # Sicherheitsprüfung auch serverseitig: Ein direkter API-Aufruf darf den
    # Verpackt-Status nicht vor Abschluss von Linie und Prüfung setzen.
    if packaging_supplied and packaged:
        try:
            line_done, inspection_done = _get_erp_completion_status(order)
        except Exception:
            current_app.logger.exception('E-Mob-Fertigstatus konnte nicht geprüft werden.')
            return jsonify(
                success=False,
                error='Fertigstatus konnte nicht geprüft werden. Verpacken wurde nicht gespeichert.'
            ), 503
        if not line_done or not inspection_done:
            return jsonify(
                success=False,
                error='Verpackt kann erst gesetzt werden, wenn Linie und Prüfung fertig sind.'
            ), 409

    try:
        matching_infos = AuftragInfo.query.filter_by(fa_nr=order).all()
        if not matching_infos:
            matching_infos = AuftragInfo.query.filter_by(fa_nr=_fa_key(order)).all()
        if not matching_infos:
            # Fallback für historische Datensätze mit abweichendem SQL-Datentyp.
            matching_infos = [
                item for item in AuftragInfo.query.all()
                if _fa_key(getattr(item, 'fa_nr', None)) == _fa_key(order)
            ]

        if not matching_infos:
            db.session.add(AuftragInfo(fa_nr=order, fa_bemerk=comment, fa_mat=0))
        else:
            # Bei vorhandenen Dubletten alle Zeilen aktualisieren, damit beim
            # nächsten Laden keine leere Dublette die Bemerkung verdeckt.
            for info_row in matching_infos:
                info_row.fa_bemerk = comment

        if packaging_supplied:
            _ensure_emob_packing_table()
            packing = EmobPackingStatus.query.filter_by(fa_nr=order).first()
            if packing is None:
                packing = EmobPackingStatus(fa_nr=order, verpackt=packaged)
                db.session.add(packing)
            else:
                packing.verpackt = packaged

        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('E-Mob-Bemerkung/Verpackt-Status konnte nicht gespeichert werden.')
        return jsonify(success=False, error='Speichern fehlgeschlagen.'), 500
    return jsonify(success=True, comment=comment, verpackt=packaged if packaging_supplied else None)


# ---------------------------------------------------------------------------
# Mengenuebersicht je Montagezelle und Woche (/kapa-emob-mengen)
# Eigene, schlanke Abfrage: je Fertigungsauftrag und Zelle nur eine Zeile (GROUP BY),
# nur Status 20 bis 60 (wie Wochenuebersicht), keine Projekt-, Fertigstatus- oder Textjoins.
# Erzeugniszeilen (Typ E) ohne Statusfilter, wie in der Wochenuebersicht.
# Einplanung: Vormontage nach StartTermPlan, Endmontage nach EndTermPlan (ISO-KW). Gefertigt = Menge minus Restmenge der E-Zeile.
# ---------------------------------------------------------------------------
MENGEN_CELLS = [
    ('2440-18', 'HAK'),
    ('2440-17', 'Anschlussmodul'),
    ('2440-14', 'Endmontage'),
]
MENGEN_WEEKS_AHEAD = 24
MENGEN_WEEKS_BACK = 8
MENGEN_STATUS_MIN = 20
MENGEN_STATUS_MAX = 60

# Maximale Stueckzahl je Montagezelle und Woche (fester Wert fuer alle Wochen).
# None = noch nicht hinterlegt -> Auslastung wird als "–" angezeigt.
MENGEN_CAPACITY_PCS = {
    '2440-18': 68,   # HAK
    '2440-17': 88,   # Anschlussmodul
    '2440-14': 88,   # Endmontage
}
MENGEN_UTIL_WARN = 0.85   # ab hier gelb
MENGEN_UTIL_OVER = 1.00   # ab hier rot


def _util_class(util):
    if util is None:
        return 'none'
    if util > MENGEN_UTIL_OVER:
        return 'over'
    if util > MENGEN_UTIL_WARN:
        return 'warn'
    return 'ok'

MENGEN_SQL = """
WITH A_ZEILEN AS (
    SELECT F.Auftrag,
           F.PmNr,
           MIN(F.Zustand)       AS Zustand,
           MAX(F.Mng)           AS Mng,
           MIN(F.StartTermPlan) AS StartTermPlan,
           MIN(F.EndTermPlan)   AS EndTermPlan
    FROM INFRADB.dbo.FAPOS AS F WITH (NOLOCK)
    JOIN INFRADB.dbo.TEILE AS T WITH (NOLOCK)
      ON T.Teil = F.Teil
    WHERE T.Gruppe = ?
      AND F.Typ = 'A'
      AND F.Stat <> 'Z'
      AND F.PmNr IN (?, ?, ?)
      AND F.Zustand BETWEEN ? AND ?
      AND F.StartTermPlan < ?
      AND (F.StartTermPlan >= ? OR F.Zustand < ? OR F.EndTermPlan >= ?)
    GROUP BY F.Auftrag, F.PmNr
),
E_ZEILEN AS (
    SELECT E.Auftrag,
           COUNT(*)        AS EZeilen,
           MAX(E.MngRest)  AS Restmenge
    FROM INFRADB.dbo.FAPOS AS E WITH (NOLOCK)
    WHERE E.Typ = 'E'
      AND E.Auftrag IN (SELECT Auftrag FROM A_ZEILEN)
    GROUP BY E.Auftrag
)
SELECT A.Auftrag, A.PmNr, A.Zustand, A.Mng, A.StartTermPlan, A.EndTermPlan,
       E.EZeilen, E.Restmenge
FROM A_ZEILEN AS A
LEFT JOIN E_ZEILEN AS E
  ON E.Auftrag = A.Auftrag
"""


def get_mengen_weeks(reference=None, ahead=MENGEN_WEEKS_AHEAD, back=0):
    """Die `back` vergangenen Wochen, die aktuelle KW und die naechsten `ahead` Wochen als (Jahr, KW)."""
    reference = reference or datetime.now()
    iso = reference.isocalendar()
    monday = datetime.fromisocalendar(int(iso[0]), int(iso[1]), 1)
    keys = []
    for offset in range(-back, ahead + 1):
        y, w, _ = (monday + timedelta(weeks=offset)).isocalendar()
        keys.append((int(y), int(w)))
    return keys


def get_mengen_records(gruppe, current_monday, date_max):
    """Liest je FA und Zelle eine Zeile. Enthaelt Rueckstand (offen vor aktueller KW) und alle Wochen bis date_max."""
    codes = [code for code, _ in MENGEN_CELLS]
    params = (
        gruppe,
        *codes,
        MENGEN_STATUS_MIN, MENGEN_STATUS_MAX,   # A-Zeilen Status
        date_max,                               # Starttermin unter Horizont
        current_monday, 60, current_monday,     # ab aktueller KW oder noch offen bzw. Endtermin ab aktueller KW
    )
    started = time.perf_counter()
    conn = None
    try:
        conn = pyodbc.connect(connectionString)
        conn.timeout = 60
        cursor = conn.cursor()
        cursor.execute(MENGEN_SQL, params)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        _debug_emob(f"Mengen-Abfrage: {len(rows)} Zeilen in {time.perf_counter() - started:.2f} s")
        return rows
    finally:
        if conn is not None:
            conn.close()


def build_mengen_overview(rows, weeks, reference=None):
    """Rueckstand als erste Zeile, danach je KW: Geplant, Gefertigt und FA-Anzahl je Zelle."""
    reference = reference or datetime.now()
    cell_codes = {code for code, _ in MENGEN_CELLS}
    visible_set = set(weeks)
    current_key = get_mengen_weeks(reference, 0)[0]
    backlog_monday = datetime.fromisocalendar(*weeks[0], 1)

    agg = defaultdict(lambda: {code: {'qty': 0.0, 'done': 0.0, 'done_known': True, 'fa': 0}
                               for code, _ in MENGEN_CELLS})
    for row in rows:
        pmnr = _text(row.get('PmNr'))
        order = _fa_key(row.get('Auftrag'))
        plan_date = row.get('EndTermPlan') if pmnr == ENDMONTAGE_CODE else row.get('StartTermPlan')
        if pmnr not in cell_codes or not hasattr(plan_date, 'isocalendar') or not order:
            continue
        y, w, _ = plan_date.isocalendar()
        key = (int(y), int(w))
        if key in visible_set:
            bucket = key
        elif key < current_key:
            # Aelter als der Betrachtungszeitraum: nur offene Auftraege im Rueckstand.
            if _number(row.get('Zustand'), -1) == 60:
                continue
            bucket = 'backlog'
        else:
            continue

        qty = _number(row.get('Mng'))
        e_count = _number(row.get('EZeilen'), None)
        remaining = _number(row.get('Restmenge'), None)
        if e_count != 1:
            remaining = None  # keine oder mehrdeutige Erzeugniszeile: Gefertigt nicht ermittelbar

        t = agg[bucket][pmnr]
        t['qty'] += qty
        t['fa'] += 1
        if remaining is None:
            t['done_known'] = False
        else:
            t['done'] += qty - remaining

    def make_cells(key):
        cells = {}
        for code, name in MENGEN_CELLS:
            t = agg[key][code]
            capacity = MENGEN_CAPACITY_PCS.get(code)
            util = None
            if key != 'backlog' and capacity and capacity > 0:
                util = t['qty'] / capacity
            cells[code] = {'name': name, 'qty': t['qty'], 'fa': t['fa'],
                           'done': t['done'] if t['done_known'] else None,
                           'capacity': capacity, 'util': util,
                           'util_class': _util_class(util)}
        return cells

    result = [{
        'label': 'Rückstand',
        'year': None,
        'range': f'Start vor {backlog_monday:%d.%m.%Y}',
        'current': False,
        'backlog': True,
        'cells': make_cells('backlog'),
    }]
    for key in weeks:
        year, week = key
        monday = datetime.fromisocalendar(year, week, 1)
        result.append({
            'label': f'KW {week:02d}',
            'year': year,
            'range': f'{monday:%d.%m.} - {monday + timedelta(days=6):%d.%m.%Y}',
            'current': key == current_key,
            'past': key < current_key,
            'backlog': False,
            'cells': make_cells(key),
        })
    return result


MENGEN_CHART_COLORS = {'2440-18': '#2563eb', '2440-17': '#16a34a', '2440-14': '#dc2626'}


def _nice_axis(value, intervals=5):
    """Liefert (Achsenmaximum, Schrittweite) mit glatten Schritten (1, 2, 2.5, 5 x 10^n)."""
    if value <= 0:
        return intervals, 1
    steps = sorted(factor * 10 ** exponent for exponent in range(-1, 8) for factor in (1, 2, 2.5, 5))
    for step in steps:
        count = math.ceil(round(value / step, 9))
        if count <= intervals:
            return round(count * step, 9), step
    return value, value / intervals


def build_mengen_chart_svg(rows, cells):
    """Liniendiagramm der geplanten Mengen je Montagezelle und KW (SVG, ohne externe Skripte)."""
    week_rows = [row for row in rows if not row['backlog']]
    if not week_rows:
        return ''
    width, height = 960, 180
    left, right, top, bottom = 56, 16, 36, 44
    plot_w = width - left - right
    plot_h = height - top - bottom
    raw_max = max([cell['qty'] for row in week_rows for cell in row['cells'].values()] + [1])
    max_val, tick_step = _nice_axis(raw_max)  # Y-Achse endet knapp ueber dem hoechsten Wert
    count = len(week_rows)

    def x_pos(index):
        return left + (plot_w * index / (count - 1) if count > 1 else plot_w / 2)

    def y_pos(value):
        return top + plot_h * (1 - value / max_val)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Geplante Mengen je Montagezelle und Woche" class="mengen-chart" '
             f'style="width:100%;height:auto">']
    # Legende
    legend_x = left
    for code, name in cells:
        color = MENGEN_CHART_COLORS.get(code, '#374151')
        parts.append(f'<line x1="{legend_x}" x2="{legend_x + 22}" y1="10" y2="10" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x + 28}" y="14" font-size="12" fill="#111827">{name}</text>')
        legend_x += 150
    # Gitter und Y-Achse
    tick_count = round(max_val / tick_step)
    for k in range(tick_count + 1):
        value = tick_step * k
        y = y_pos(value)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{round(value)}</text>')
    # Aktuelle Woche markieren
    for index, row in enumerate(week_rows):
        if row['current']:
            x = x_pos(index)
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top + plot_h}" stroke="#9ca3af" stroke-dasharray="4 4"/>')
            parts.append(f'<text x="{x:.1f}" y="{top - 8}" text-anchor="middle" font-size="11" fill="#111827">aktuell</text>')
    # X-Achse
    for index, row in enumerate(week_rows):
        x = x_pos(index)
        weight = '700' if row['current'] else '400'
        color = '#111827' if not row['past'] else '#6b7280'
        anchor_y = top + plot_h + 8
        parts.append(f'<text x="{x:.1f}" y="{anchor_y}" transform="rotate(-90 {x:.1f} {anchor_y})" '
                     f'text-anchor="end" dominant-baseline="middle" font-size="11" '
                     f'font-weight="{weight}" fill="{color}">{row["label"]}</text>')
    # Linien je Zelle
    for code, name in cells:
        color = MENGEN_CHART_COLORS.get(code, '#374151')
        points = [(x_pos(i), y_pos(row['cells'][code]['qty'])) for i, row in enumerate(week_rows)]
        path = ' '.join(f'{px:.1f},{py:.1f}' for px, py in points)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, (px, py) in enumerate(points):
            qty = week_rows[i]['cells'][code]['qty']
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}">'
                         f'<title>{name} {week_rows[i]["label"]}: {round(qty)} St.</title></circle>')
    parts.append('</svg>')
    return ''.join(parts)


@app.route('/kapa-emob-mengen', methods=['GET'])
def kapa_emob_mengen_index():
    now = datetime.now()
    weeks = get_mengen_weeks(now, MENGEN_WEEKS_AHEAD, MENGEN_WEEKS_BACK)
    lookback_monday = datetime.fromisocalendar(*weeks[0], 1)
    date_max = datetime.fromisocalendar(*weeks[-1], 1) + timedelta(weeks=1)
    records = get_mengen_records(session.get('abteilung', 'M1'), lookback_monday, date_max)
    rows = build_mengen_overview(records, weeks, reference=now)
    chart_svg = build_mengen_chart_svg(rows, MENGEN_CELLS)
    return render_template('kapa_emob_mengen.html', rows=rows, cells=MENGEN_CELLS,
                           cells_capacity=MENGEN_CAPACITY_PCS, chart_svg=chart_svg,
                           generated=now, first_week=weeks[0], last_week=weeks[-1])

# ---------------------------------------------------------------------------
# Produktionsmonitor HAK (/2440-18)
# Schreibgeschuetzte Anzeige fuer den Shopfloor: Rueckstand, aktuelle KW,
# naechste KW. Die Daten werden von der HTML-Seite alle 5 Minuten per API
# nachgeladen, ohne sichtbaren Seitenwechsel.
# ---------------------------------------------------------------------------
HAK_MONITOR_PMR = '2440-18'
HAK_MONITOR_NAME = 'HAK'
HAK_MONITOR_REFRESH_SECONDS = 300


def _monitor_job(job):
    """Wandelt einen Wochenplan-Auftrag in JSON-freundliche Monitorwerte um."""
    manufactured = job.get('MngGefertigt')
    return {
        'start': job['Start'].strftime('%d.%m.%Y') if hasattr(job.get('Start'), 'strftime') else _text(job.get('Start')),
        'order': _text(job.get('Auftrag')),
        'status': _text(job.get('Zustand')),
        'part': _text(job.get('Teil')),
        'description': _text(job.get('Bez')),
        'quantity_done': None if manufactured is None else round(_number(manufactured)),
        'quantity_total': round(_number(job.get('Mng'))),
        'project': _text(job.get('Projekt')) or '—',
        'project_name': _text(job.get('Projektbezeichnung')) or '—',
        'serial': '-'.join(filter(None, [_text(job.get('SerienNr')), _text(job.get('SerienNrBis'))])) or '—',
        'comment': _text(job.get('Kommentar')),
    }


def _get_hak_monitor_payload(now=None):
    """Liest die HAK-Daten fuer Rueckstand, aktuelle und naechste KW."""
    now = now or datetime.now()
    iso = now.isocalendar()
    current_key = (int(iso[0]), int(iso[1]))
    weeks = get_planning_weeks(now, before=0, after=1)
    date_max = datetime.fromisocalendar(*weeks[-1], 1) + timedelta(weeks=1)

    records = get_emob_jobs(session.get('abteilung', 'M1'), None, date_max, durchlauf=True)
    plan = build_emob_week_plan(
        records,
        AuftragInfo.query.all(),
        weeks,
        capacities={},
        reference=now,
        packing_states=_get_emob_packing_states(),
        durchlauf=True,
    )

    sections = []
    for week in plan:
        block = next((item for item in week['blocks'] if item['pmnr'] == HAK_MONITOR_PMR), None)
        jobs = block['jobs'] if block else []
        sections.append({
            'key': 'backlog' if week['is_backlog'] else f"{week['year']}-KW-{week['week']:02d}",
            'label': week['label'],
            'date_range': week['date_range'],
            'is_backlog': week['is_backlog'],
            'is_current': (
                not week['is_backlog']
                and (week['year'], week['week']) == current_key
            ),
            'quantity_total': round(_number(block['quantity_sum'])) if block else 0,
            'quantity_done': (
                None if block is None or block['manufactured_quantity_sum'] is None
                else round(_number(block['manufactured_quantity_sum']))
            ),
            'order_count': len(jobs),
            'jobs': [_monitor_job(job) for job in jobs],
        })

    return {
        'cell': HAK_MONITOR_PMR,
        'cell_name': HAK_MONITOR_NAME,
        'generated_at': now.strftime('%d.%m.%Y %H:%M:%S'),
        'refresh_seconds': HAK_MONITOR_REFRESH_SECONDS,
        'sections': sections,
    }


@app.route('/2440-18', methods=['GET'])
def kapa_emob_monitor_hak():
    """Schreibgeschuetzter Produktionsmonitor fuer die HAK-Zelle."""
    now = datetime.now()
    payload = _get_hak_monitor_payload(now)
    return render_template('kapa_emob_monitor_hak.html', monitor=payload)


@app.route('/api/2440-18', methods=['GET'])
def kapa_emob_monitor_hak_api():
    """JSON-Endpunkt fuer die automatische Monitor-Aktualisierung."""
    response = jsonify(_get_hak_monitor_payload(datetime.now()))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response
