import pyodbc

from infraDB_function import CheckFAMat
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, session
import datetime as dt
from datetime import datetime, timedelta
from config import connectionString
from collections import defaultdict
import os
import csv
import json
import uuid


# PmNr-Zuordnung für die fünf Teams.


TEAM_CONFIG = {
    'E-Mobility': ('2440-14', '2450-11', '2440-18', '2440-16'),
    'Kabelkonfektion': ('2440-13', '2440-20'),
    'ESD-Montage': ('2440-12',),
    'Systembaugruppen': (),
    'QS': ('2450-10', '2450-11', '2450-12', '8700-11'),
}

# PmNr, deren Aufträge in der Kapazitätsplanung nicht angezeigt werden.
PMNR_BLACKLIST = ('2440-14', '2450-11', '2440-18', '2440-16', )

# Teilenummern, deren Aufträge in der Kapazitätsplanung nicht angezeigt werden.
TEIL_BLACKLIST = ('NZ_73', 'NZ_60', 'NA_M1', 'Linie_L/S_1', 'NZ_62', 'REPARATUR TE',)

PM_TO_TEAM = {
    pmnr: team
    for team, pmnrs in TEAM_CONFIG.items()
    for pmnr in pmnrs
}

def _team_for_pmnr(value):
    """Ordnet Arbeitsplatznummern den Teams zu; 2560* gehört zur QS."""
    pmnr_text = _pmnr(value)
    if pmnr_text.startswith('2560'):
        return 'Qualitätssicherung'
    return PM_TO_TEAM.get(pmnr_text)


def _value(record, *names):
    """Liest ein Feld tolerant aus SQLAlchemy-Objekten oder Dictionaries."""
    if record is None:
        return None
    for name in names:
        if isinstance(record, dict) and name in record:
            return record[name]
        try:
            value = getattr(record, name)
        except (AttributeError, TypeError):
            continue
        if value is not None:
            return value
    return None


def _text(value):
    return '' if value is None else str(value).strip()


def _number(value, default=0.0):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pmnr(value):
    return _text(value)


def _normalise_team(value):
    value = _text(value).casefold()
    if not value:
        return None
    aliases = {
        'e mobility': 'E-Mobility',
        'e-mobility': 'E-Mobility',
        'kabel': 'Kabelkonfektion',
        'kabelkonfektion': 'Kabelkonfektion',
        'esd': 'ESD-Montage',
        'esd-montage': 'ESD-Montage',
        'esd baugruppen': 'ESD-Montage',
        'systembaugruppen': 'Systembaugruppen',
        'system baugruppen': 'Systembaugruppen',
    }
    return aliases.get(value)


def _safe_model_rows(model):
    try:
        return model.query.all()
    except Exception:
        # Die Kapazitätsplanung bleibt auch dann aufrufbar, wenn eine optionale
        # Personal-/Stunden-Tabelle in einer Umgebung nicht vorhanden ist.
        return []


def _person_key(record):
    value = _value(
        record,
        'PersNr', 'PersonalNr', 'MitarbeiterNr', 'MitarbeiterID',
        'PersonalID', 'PersonalId', 'person_id', 'id'
    )
    return _text(value) if value is not None else None


def _week_of(record):
    year = _value(record, 'Jahr', 'jahr', 'Year', 'year', 'Kalenderjahr')
    week = _value(record, 'KW', 'Kw', 'kw', 'Kalenderwoche', 'Woche', 'week')
    if year is not None and week is not None:
        try:
            return int(year), int(week)
        except (TypeError, ValueError):
            pass

    date_value = _value(record, 'Datum', 'datum', 'Date', 'date', 'Tag')
    if date_value is not None and hasattr(date_value, 'isocalendar'):
        iso = date_value.isocalendar()
        return int(iso[0]), int(iso[1])
    return None


def _weekly_hours(record):
    # StundenKW kann je nach Modell Stunden oder Minuten führen.
    minutes = _value(record, 'Minuten', 'Produktionsminuten')
    if minutes is not None:
        return _number(minutes) / 60.0
    hours = _value(
        record,
        'Stunden', 'StundenKW', 'Sollstunden', 'Wochenstunden',
        'Arbeitsstunden', 'Hours', 'Kapazitaet', 'Kapazität', 'Std'
    )
    return _number(hours) if hours is not None else None


def get_weekly_capacity(week_keys):
    """Liest Kapazitäten aus der Teamleiter-Datei und liefert sie je Woche."""
    # Die Teamleiterverwaltung ist die führende Quelle, sobald ihre Datei
    # vorhanden ist. Damit fließen dieselben Werte in die Hauptmatrix ein.
    if os.path.exists(TEAMLEITER_DATA_FILE):
        data = _load_teamleiter_data()
        return {
            key: {
                team: values['available']
                for team, values in _teamleiter_capacity(data, key[0], key[1]).items()
            }
            for key in week_keys
        }

    # Rückwärtskompatibler Fallback für eine eventuell noch vorhandene
    # Datenbankpflege.
    capacity = {key: {team: 0.0 for team in TEAM_CONFIG} for key in week_keys}
    weekly_seen = set()
    personal_by_id = {}
    personal_defaults = {team: 0.0 for team in TEAM_CONFIG}

    for person in _safe_model_rows(Personal):
        team = _normalise_team(_value(
            person, 'Team', 'team', 'Bereich', 'bereich',
            'Abteilung', 'abteilung', 'Gruppe', 'gruppe'
        ))
        person_id = _person_key(person)
        if team and person_id:
            personal_by_id[person_id] = team
        if team:
            default_hours = _weekly_hours(person)
            if default_hours is not None:
                personal_defaults[team] += default_hours

    for row in _safe_model_rows(StundenKW):
        week_key = _week_of(row)
        if week_key not in capacity:
            continue

        team = _normalise_team(_value(
            row, 'Team', 'team', 'Bereich', 'bereich',
            'Abteilung', 'abteilung', 'Gruppe', 'gruppe'
        ))
        person_id = _person_key(row)
        if team is None and person_id:
            team = personal_by_id.get(person_id)
        if team is None:
            related_person = _value(row, 'Personal', 'personal', 'Mitarbeiter', 'mitarbeiter')
            team = _normalise_team(_value(
                related_person, 'Team', 'team', 'Bereich', 'bereich',
                'Abteilung', 'abteilung', 'Gruppe', 'gruppe'
            ))

        hours = _weekly_hours(row)
        if team in TEAM_CONFIG and hours is not None:
            capacity[week_key][team] += hours
            weekly_seen.add((week_key, team))

    for week_key in week_keys:
        for team, hours in personal_defaults.items():
            if (week_key, team) not in weekly_seen:
                capacity[week_key][team] = hours

    return capacity


def _order_info_map(auftrag_info):
    info_by_order = {}
    for info in auftrag_info:
        order_number = _value(info, 'fa_nr', 'FANr', 'Auftrag', 'auftrag')
        if order_number is None:
            continue
        info_by_order[_text(order_number)] = {
            'comment': _text(_value(info, 'fa_bemerk', 'Bemerkung', 'Kommentar')),
            'material_complete': _number(_value(info, 'fa_mat', 'MaterialKomplett')) == 1,
        }
    return info_by_order


def _unique_display_values(*values):
    """Führt mehrere Werte zusammen und entfernt doppelte Anzeigeeinträge."""
    result = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return ', '.join(result)


def _sort_jobs_for_week(jobs):
    """Mischt Aufträge ohne QS nach Team und stellt reine QS-Aufträge ans Ende."""
    team_order = {
        'E-Mobility': 0,
        'Kabelkonfektion': 1,
        'ESD-Montage': 2,
        'Systembaugruppen': 3,
    }

    def sort_key(job):
        active_teams = {
            team for team, load in job.get('TeamLoads', {}).items()
            if load.get('minutes', 0) > 0
        }
        non_qs_teams = active_teams.intersection(team_order)
        has_qs = 'QS' in active_teams
        is_qs_only = has_qs and not non_qs_teams
        is_mixed_without_qs = len(non_qs_teams) > 1
        first_team = min(
            (team_order[team] for team in non_qs_teams),
            default=len(team_order)
        )

        return (
            2 if is_qs_only else 0 if is_mixed_without_qs else 1,
            first_team,
            _text(job.get('Auftrag')),
        )

    return sorted(jobs, key=sort_key)


def _merge_week_jobs(jobs):
    """Fasst gleiche Aufträge innerhalb einer KW zu einer Zeile zusammen.

    Die Produktionszeiten werden je Team/Maschinengruppe addiert. Dadurch
    bleiben unterschiedliche PmNr eines Auftrags in den Teamspalten sichtbar,
    während der Auftrag selbst nur einmal erscheint.
    """
    merged = {}

    for index, job in enumerate(jobs):
        order_key = _text(job.get('Auftrag'))
        # Leere Auftragsnummern dürfen nicht versehentlich zu einer Sammelzeile
        # zusammenlaufen.
        key = order_key or f'__row_{index}'

        if key not in merged:
            merged[key] = dict(job)
            merged[key]['TeamLoads'] = {
                team: {
                    'minutes': load.get('minutes', 0.0),
                    'hours': load.get('hours', 0.0),
                    'pmnrs': list(load.get('pmnrs', [])),
                }
                for team, load in job.get('TeamLoads', {}).items()
            }
            continue

        target = merged[key]
        target['Mng'] = max(_number(target.get('Mng')), _number(job.get('Mng')))
        target['ZeitMinuten'] += _number(job.get('ZeitMinuten'))
        target['ZeitStunden'] = target['ZeitMinuten'] / 60.0
        target['PmNr'] = _unique_display_values(target.get('PmNr'), job.get('PmNr'))
        target['Projekt'] = _unique_display_values(target.get('Projekt'), job.get('Projekt'))
        target['Teil'] = _unique_display_values(target.get('Teil'), job.get('Teil'))
        target['Bez'] = _unique_display_values(target.get('Bez'), job.get('Bez'))
        target['Kommentar'] = _unique_display_values(target.get('Kommentar'), job.get('Kommentar'))
        target['MaterialKomplett'] = bool(target.get('MaterialKomplett')) or bool(job.get('MaterialKomplett'))
        target['UnassignedMinutes'] += _number(job.get('UnassignedMinutes'))
        target['UnassignedPmNrs'] = list(dict.fromkeys(
            target.get('UnassignedPmNrs', []) + job.get('UnassignedPmNrs', [])
        ))

        if job.get('Start') is not None and (target.get('Start') is None or job['Start'] < target['Start']):
            target['Start'] = job['Start']
        if job.get('Ende') is not None and (target.get('Ende') is None or job['Ende'] > target['Ende']):
            target['Ende'] = job['Ende']

        for team, source_load in job.get('TeamLoads', {}).items():
            target_load = target['TeamLoads'].setdefault(
                team, {'minutes': 0.0, 'hours': 0.0, 'pmnrs': []}
            )
            target_load['minutes'] += _number(source_load.get('minutes'))
            target_load['hours'] = target_load['minutes'] / 60.0
            target_load['pmnrs'] = list(dict.fromkeys(
                target_load.get('pmnrs', []) + source_load.get('pmnrs', [])
            ))

    return list(merged.values())


def _build_project_groups(jobs):
    """Baut Summenzeilen nur aus Projekten mit mindestens zwei FA-Nummern."""
    grouped = {}
    order_keys_by_project = defaultdict(set)

    for job in jobs:
        project = _text(job.get('Projekt'))
        if not project:
            continue

        group = grouped.setdefault(project, {
            'Projekt': project,
            'Zustand': job.get('Zustand', ''),
            'AuftragAnzahl': 0,
            'Menge': 0.0,
            'ZeitStunden': 0.0,
            'TeamLoads': {
                team: {'minutes': 0.0, 'hours': 0.0, 'pmnrs': []}
                for team in TEAM_CONFIG
            },
            'jobs': [],
        })
        order_key = _text(job.get('Auftrag'))
        if order_key:
            order_keys_by_project[project].add(order_key)
        group['Menge'] += _number(job.get('Mng'))
        group['ZeitStunden'] += _number(job.get('ZeitMinuten')) / 60.0
        group['jobs'].append(job)

        for team, source_load in job.get('TeamLoads', {}).items():
            target_load = group['TeamLoads'][team]
            target_load['minutes'] += _number(source_load.get('minutes'))
            target_load['hours'] = target_load['minutes'] / 60.0
            target_load['pmnrs'] = list(dict.fromkeys(
                target_load['pmnrs'] + source_load.get('pmnrs', [])
            ))

    # Entscheidend ist die Zahl verschiedener Auftragsnummern (FA), nicht die
    # Zahl der Datensätze oder Maschinengruppen innerhalb eines Auftrags.
    result = []
    for project, group in grouped.items():
        group['AuftragAnzahl'] = len(order_keys_by_project[project])
        if group['AuftragAnzahl'] >= 2:
            result.append(group)
    return result


def build_week_plan(records, auftrag_info, week_keys):
    """Baut eine Wochenplanung mit einer Zeile je Auftrag und Kalenderwoche."""
    info_by_order = _order_info_map(auftrag_info)
    grouped = defaultdict(list)

    for rec in records:
        zustand, auftrag, teil, bez, mng, start_term, end_term, zeit, pmnr, proj, _ = rec
        if start_term is None or not hasattr(start_term, 'isocalendar'):
            continue

        end_value = end_term if end_term is not None and hasattr(end_term, 'isocalendar') else start_term
        start_monday = start_term - timedelta(days=start_term.weekday())
        end_monday = end_value - timedelta(days=end_value.weekday())
        start_week_key = (int(start_monday.isocalendar()[0]), int(start_monday.isocalendar()[1]))
        end_week_key = (int(end_monday.isocalendar()[0]), int(end_monday.isocalendar()[1]))
        total_planned_weeks = max(1, ((end_monday - start_monday).days // 7) + 1)
        visible_week_keys = [
            candidate_key for candidate_key in week_keys
            if start_week_key <= candidate_key <= end_week_key
        ]
        if not visible_week_keys:
            continue

        order_key = _text(auftrag)
        info = info_by_order.get(order_key, {})
        pmnr_text = _pmnr(pmnr)
        minutes = _number(zeit)
        weekly_minutes = minutes / total_planned_weeks
        team = _team_for_pmnr(pmnr_text)

        for current_week_key in visible_week_keys:
            current_monday = datetime.fromisocalendar(
                current_week_key[0], current_week_key[1], 1
            )
            week_position = ((current_monday - start_monday).days // 7) + 1
            team_loads = {
                team_name: {'minutes': 0.0, 'hours': 0.0, 'pmnrs': []}
                for team_name in TEAM_CONFIG
            }
            if team in TEAM_CONFIG:
                team_loads[team] = {
                    'minutes': weekly_minutes,
                    'hours': weekly_minutes / 60.0,
                    'pmnrs': [pmnr_text] if pmnr_text else [],
                }

            grouped[current_week_key].append({
                'Zustand': _text(zustand),
                'Auftrag': auftrag,
                'Projekt': _text(proj),
                'Teil': _text(teil),
                'Bez': _text(bez),
                'Mng': _number(mng),
                'Start': start_term,
                'Ende': end_value,
                'ZeitMinuten': weekly_minutes,
                'ZeitStunden': weekly_minutes / 60.0,
                'PmNr': pmnr_text,
                'Team': team,
                'Typ': 'Start',
                'Wochenindex': week_position,
                'Wochenanzahl': total_planned_weeks,
                'TeamLoads': team_loads,
                'UnassignedMinutes': weekly_minutes if team not in TEAM_CONFIG else 0.0,
                'UnassignedPmNrs': [pmnr_text] if team not in TEAM_CONFIG and pmnr_text else [],
                'Kommentar': info.get('comment', ''),
                'MaterialKomplett': info.get('material_complete', False),
            })

    capacity_by_week = get_weekly_capacity(week_keys)
    plan = []
    for year, week in week_keys:
        key = (year, week)
        jobs = sorted(
            grouped.get(key, []),
            key=lambda item: (
                item['Start'],
                _text(item['Auftrag']),
                _text(item['PmNr'])
            )
        )
        jobs = _merge_week_jobs(jobs)
        jobs = _sort_jobs_for_week(jobs)

        load_by_team = {team: 0.0 for team in TEAM_CONFIG}
        unassigned_minutes = 0.0
        unassigned_pmnrs = set()
        for job in jobs:
            for team, team_load in job['TeamLoads'].items():
                load_by_team[team] += team_load['minutes']
            unassigned_minutes += job['UnassignedMinutes']
            unassigned_pmnrs.update(job.get('UnassignedPmNrs', []))

        metrics = {}
        for team in TEAM_CONFIG:
            load_hours = load_by_team[team] / 60.0
            capacity_hours = capacity_by_week[key].get(team, 0.0)
            utilisation = (load_hours / capacity_hours * 100.0) if capacity_hours else 0.0
            metrics[team] = {
                'load_hours': load_hours,
                'capacity_hours': capacity_hours,
                'utilisation': utilisation,
                'utilisation_width': min(utilisation, 100.0),
                'status': 'over' if utilisation > 100.0 else ('near' if utilisation >= 85.0 else 'ok'),
            }

        week_start = datetime.fromisocalendar(year, week, 1)
        week_end = week_start + timedelta(days=6)
        summary_groups = _build_project_groups(jobs)
        summary_project_numbers = {
            _text(group.get('Projekt')) for group in summary_groups
        }
        normal_jobs = [
            job for job in jobs
            if not _text(job.get('Projekt'))
            or _text(job.get('Projekt')) not in summary_project_numbers
        ]

        plan.append({
            'year': year,
            'week': week,
            'label': f'KW {week:02d}',
            'date_range': f'{week_start:%d.%m.} - {week_end:%d.%m.%Y}',
            'jobs': jobs,
            'metrics': metrics,
            'unassigned_hours': unassigned_minutes / 60.0,
                'unassigned_pmnrs': sorted(unassigned_pmnrs),
            'project_groups': summary_groups,
            'normal_jobs': normal_jobs,
        })
    return plan


@app.route('/update_kapa_remark', methods=['POST'])
def update_kapa_remark():
    """Speichert die zentrale Bemerkung eines Fertigungsauftrags."""
    data = request.get_json(silent=True) or {}
    fa_nr = _text(data.get('fa_nr'))
    comment = _text(data.get('comment'))

    if not fa_nr:
        return jsonify({'success': False, 'error': 'Keine FA-Nummer angegeben.'}), 400

    if len(comment) > 2000:
        return jsonify({'success': False, 'error': 'Die Bemerkung darf maximal 2000 Zeichen enthalten.'}), 400

    info = AuftragInfo.query.filter_by(fa_nr=fa_nr).first()
    if info is None:
        info = AuftragInfo(fa_nr=fa_nr, fa_bemerk=comment, fa_mat=0)
        db.session.add(info)
    else:
        info.fa_bemerk = comment

    db.session.commit()
    return jsonify({'success': True, 'comment': comment})


def get_planning_weeks(reference_date=None, before=6, after=6):
    reference_date = reference_date or datetime.now()
    monday = reference_date - timedelta(days=reference_date.weekday())
    weeks = []
    for offset in range(-before, after + 1):
        date_value = monday + timedelta(weeks=offset)
        iso = date_value.isocalendar()
        weeks.append((int(iso[0]), int(iso[1])))
    return weeks


def getJobs_weekly(Gruppe, ZustandMin, ZustandMax, DateMin, DateMax):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        blacklist_placeholders = ', '.join('?' for _ in PMNR_BLACKLIST)
        teil_blacklist_placeholders = ', '.join('?' for _ in TEIL_BLACKLIST)
        sql_query = f"""
            SELECT
                FAPOS.Zustand,
                FAPOS.Auftrag,
                FAPOS.Teil,
                TEILE.Bez,
                FAPOS.Mng,
                FAPOS.StartTermPlan,
                FAPOS.EndTermPlan,
                FAPOS.Zeit,
                FAPOS.PmNr,
                COALESCE(CONVERT(varchar(100), FAPOS.Proj), '') AS Projektnummer,
                DATEPART(ISO_WEEK, FAPOS.StartTermPlan) AS Kalenderwoche
            FROM INFRADB.dbo.FAPOS AS FAPOS
            JOIN INFRADB.dbo.TEILE AS TEILE ON FAPOS.Teil = TEILE.Teil
            JOIN INFRADB.dbo.ARBPLATZ AS ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
            WHERE TEILE.Gruppe = ?
              AND FAPOS.Zustand BETWEEN ? AND ?
              AND FAPOS.Typ = 'A'
              AND FAPOS.Stat <> 'E'
              AND FAPOS.PmNr NOT IN ({blacklist_placeholders})
              AND FAPOS.Teil NOT IN ({teil_blacklist_placeholders})
              AND FAPOS.EndTermPlan >= ?
              AND FAPOS.StartTermPlan < ?
            ORDER BY FAPOS.StartTermPlan, FAPOS.Auftrag
        """
        try:
            cursor = conn.cursor()
            cursor.execute(
                sql_query,
                (
                    Gruppe,
                    ZustandMin,
                    ZustandMax,
                    *PMNR_BLACKLIST,
                    *TEIL_BLACKLIST,
                    DateMin,
                    DateMax,
                )
            )
            return cursor.fetchall()
        finally:
            conn.close()





def getJobs_legacy(Gruppe, ZustandMin, ZustandMax, DateMin, DateMax):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
            SELECT 
                FAPOS.Zustand,              -- STAT
                FAPOS.Auftrag,              -- FA-Nummer
                FAPOS.Teil,                 -- GREIPL-Nr
                TEILE.Bez,                  -- Bezeichnung
                FAPOS.Mng,                  -- Menge
                FAPOS.StartTermPlan,        -- Start
                FAPOS.EndTermPlan,          -- Ende
                FAPOS.Zeit,                 -- Produktionszeit (Minuten)
                FAPOS.PmNr,                 -- Arbeitsplatz
                DATEPART(WEEK, FAPOS.StartTermPlan) AS Kalenderwoche
            FROM 
                INFRADB.dbo.FAPOS FAPOS
            JOIN 
                INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
            JOIN 
                INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
            WHERE
                TEILE.Gruppe = '{Gruppe}' 
                AND FAPOS.Zustand BETWEEN '{ZustandMin}' AND '{ZustandMax}' 
                AND FAPOS.Typ = 'A'
                AND FAPOS.Stat != 'E'
                AND FAPOS.StartTermPlan > '{DateMin}' 
                AND FAPOS.StartTermPlan < '{DateMax}'
        """
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()
        return records


def group_FA_by_week(records):
    grouped_jobs = defaultdict(list)

    for rec in records:
        zustand, auftrag, teil, bez, mng, start_term, end_term, zeit, pmnr, kw = rec

        # Für Startdatum ISO-Jahr und ISO-KW verwenden
        iso_start_year, iso_start_week, _ = start_term.isocalendar()

        start_job = {
            'Zustand': zustand,
            'Auftrag': auftrag,
            'Teil': teil,
            'Bez': bez,
            'Mng': float(mng),
            'Datum': start_term,
            'Typ': 'Start',
            'Zeit': float(zeit) if zeit else 0.0,
            'PmNr': pmnr,
            'Kalenderwoche': iso_start_week
        }
        grouped_jobs[(iso_start_year, iso_start_week)].append(start_job)

        # Für Enddatum ISO-Jahr und ISO-KW verwenden, falls vorhanden
        if end_term:
            iso_end_year, iso_end_week, _ = end_term.isocalendar()
            end_job = {
                'Zustand': zustand,
                'Auftrag': auftrag,
                'Teil': teil,
                'Bez': bez,
                'Mng': float(mng),
                'Datum': end_term,
                'Typ': 'Ende',
                'Zeit': float(zeit) if zeit else 0.0,
                'PmNr': pmnr,
                'Kalenderwoche': iso_end_week
            }
            grouped_jobs[(iso_end_year, iso_end_week)].append(end_job)

    # Sortiere die Einträge in jedem Jahr/Woche nach Auftrag und Typ (Start vor Ende)
    for key in grouped_jobs:
        grouped_jobs[key].sort(key=lambda j: (j['Auftrag'], 0 if j['Typ'] == 'Start' else 1))

    return dict(sorted(grouped_jobs.items()))


def GetFAMat(FANR, ZustandMin, ZustandMax):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
            SELECT 
                FAPOS.Auftrag,
                FAPOS.Zustand,              
                FAPOS.Teil,                 
                TEILE.Bez,                  
                FAPOS.MngRest
            FROM INFRADB.dbo.FAPOS FAPOS
            JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
            LEFT JOIN (
                SELECT 
                    Teil, 
                    COALESCE(SUM(CASE WHEN Lag != 'N' THEN Mng ELSE 0 END), 0) AS BestandSumme
                FROM INFRADB.dbo.LAGPLBST
                GROUP BY Teil
            ) LAGPLBST_SUM ON FAPOS.Teil = LAGPLBST_SUM.Teil
            WHERE
                FAPOS.Auftrag = '{FANR}'
                AND FAPOS.Zustand BETWEEN {ZustandMin} AND {ZustandMax}
                AND FAPOS.Typ = 'M'
                AND FAPOS.Stat != 'E'
                AND (FAPOS.MngRest IS NULL OR COALESCE(LAGPLBST_SUM.BestandSumme, 0) < FAPOS.MngRest)
        """
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()
        return records




# Teamleiterverwaltung: bewusst als einfache Serverdatei umgesetzt, da aktuell
# keine eigene Datenbank für Mitarbeiter und Anwesenheiten vorhanden ist.
TEAMLEITER_TEAMS = ('E-Mobility', 'Kabelkonfektion', 'ESD-Montage', 'Systembaugruppen')
TEAMLEITER_DATA_FILE = os.path.join(os.path.dirname(__file__), 'teamleiter_kapa.json')
TEAMLEITER_ABSENCE_RATE = 0.10

# Initialer Mitarbeiterstamm für die Teamleiterseite. Die Einträge werden nur
# bei einer noch leeren Datenbasis angelegt und danach normal weiter gepflegt.
TEAMLEITER_INITIAL_KABELKONFEKTION = (
    ('400', 'Friedl Brigitte', 40),
    ('403', 'Hauer Michaela', 40),
    ('480', 'Moser Siglinde', 25),
    ('571', 'Rothbauer Andrea', 20),
    ('779', 'Ertl Melanie', 24),
    ('844', 'Frank Eva-Maria', 34),
    ('845', 'Grübl Sabrina', 40),
    ('1007', 'Zettl Silke', 40),
    ('1031', 'Hopfinger Britta', 34),
    ('1056', 'Stadler Maria Elisabeth', 24),
    ('1067', 'Greova Milena', 40),
    ('1098', 'Edbauer Silvia', 40),
    ('1179', 'Schwankl Nadine', 40),
    ('1181', 'Niepel Silke', 40),
    ('1182', 'Kurzböck-Balda Christine', 20),
    ('1265', 'Müller Ivonne', 40),
    ('1271', 'Greipl Daniela', 20),
    ('1276', 'Lebedová Vlasta', 40),
)


def _teamleiter_default_data():
    return {'employees': [], 'attendance': {}, 'checkins': {}, 'daily_checkins': {}, 'settings': {'absence_rate': TEAMLEITER_ABSENCE_RATE}}


def _teamleiter_initial_employees():
    return [
        {
            'id': personnel_number,
            'personnel_number': personnel_number,
            'name': name,
            'team': 'Kabelkonfektion',
            'weekly_hours': weekly_hours,
            'active': True,
        }
        for personnel_number, name, weekly_hours in TEAMLEITER_INITIAL_KABELKONFEKTION
    ]


def _load_teamleiter_data():
    try:
        with open(TEAMLEITER_DATA_FILE, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = _teamleiter_default_data()
    defaults = _teamleiter_default_data()
    defaults.update(data if isinstance(data, dict) else {})
    defaults.setdefault('employees', [])
    defaults.setdefault('attendance', {})
    defaults.setdefault('checkins', {})
    defaults.setdefault('daily_checkins', {})
    defaults.setdefault('settings', {})
    defaults['settings'].setdefault('absence_rate', TEAMLEITER_ABSENCE_RATE)

    # Die Beispieldaten werden ergänzt, falls sie noch nicht vorhanden sind.
    # Bereits gepflegte Mitarbeiter und Anwesenheiten bleiben unverändert.
    existing_numbers = {
        str(item.get('personnel_number', ''))
        for item in defaults['employees']
    }
    missing_initial = [
        employee for employee in _teamleiter_initial_employees()
        if employee['personnel_number'] not in existing_numbers
    ]
    if missing_initial:
        defaults['employees'].extend(missing_initial)
        _save_teamleiter_data(defaults)
    return defaults


def _save_teamleiter_data(data):
    temporary_file = TEAMLEITER_DATA_FILE + '.tmp'
    with open(temporary_file, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary_file, TEAMLEITER_DATA_FILE)


def _teamleiter_week_key(year, week):
    return f'{int(year)}-KW-{int(week):02d}'


def _teamleiter_parse_week(value):
    text = _text(value).upper().replace(' ', '')
    try:
        if '-KW-' in text:
            year, week = text.split('-KW-')
        elif 'KW' in text:
            year, week = text.split('KW', 1)
            year = year.rstrip('-')
        else:
            return None
        return int(year), int(week)
    except (TypeError, ValueError):
        return None


def _teamleiter_is_current_week(year, week):
    current_iso = datetime.now().isocalendar()
    return (int(year), int(week)) == (int(current_iso[0]), int(current_iso[1]))


def _teamleiter_capacity(data, year, week):
    key = _teamleiter_week_key(year, week)
    result = {team: {'gross': 0.0, 'absence': 0.0, 'available': 0.0} for team in TEAMLEITER_TEAMS}
    absence_rate = _number(data.get('settings', {}).get('absence_rate'), TEAMLEITER_ABSENCE_RATE)
    absence_rate = min(max(absence_rate, 0.0), 1.0)

    for employee in data.get('employees', []):
        if not employee.get('active', True):
            continue
        team = employee.get('team')
        if team not in result:
            continue

        weekly_hours = max(0.0, _number(employee.get('weekly_hours')))
        entry = data.get('attendance', {}).get(key, {}).get(str(employee.get('id')), {})
        status = _text(entry.get('status')).casefold()

        # Anwesenheit wird wochenweise gepflegt. Bei Abwesenheit ist die
        # verfügbare Arbeitszeit null; bei Anwesenheit gelten die eingetragenen
        # Stunden oder ersatzweise die individuellen Wochenstunden.
        if status in {'urlaub', 'krank', 'schulung', 'sonstiges'}:
            worked_hours = 0.0
        else:
            worked_hours = _number(entry.get('hours'), weekly_hours)
            worked_hours = min(max(worked_hours, 0.0), weekly_hours)

        absence_hours = weekly_hours - worked_hours
        result[team]['gross'] += weekly_hours
        result[team]['absence'] += absence_hours
        result[team]['available'] += worked_hours * (1.0 - absence_rate)

    return result


def _teamleiter_daily_key(value=None):
    value = value or datetime.now().date()
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def _teamleiter_date_for_weekday(year, week, weekday):
    return dt.date.fromisocalendar(int(year), int(week), int(weekday))


def _teamleiter_daily_entry(data, date_value, team):
    """Liest eine Tagesmeldung robust aus der täglichen Datenstruktur.

    Neue Meldungen liegen unter daily_checkins[datum][team]['checkin'].
    Die flache Form und die alte Wochenstruktur bleiben als Rückfall erhalten.
    """
    date_key = _teamleiter_daily_key(date_value)
    daily_team_entry = data.get('daily_checkins', {}).get(date_key, {}).get(team, {}) or {}
    entry = daily_team_entry.get('checkin') if isinstance(daily_team_entry, dict) else None
    if isinstance(entry, dict):
        return entry
    if isinstance(daily_team_entry, dict) and daily_team_entry.get('checked_at'):
        return daily_team_entry
    return {}


def _teamleiter_latest_report(data, year, week, team):
    """Liefert die letzte Tagesmeldung innerhalb der ausgewählten KW."""
    latest = None
    for date_key in data.get('daily_checkins', {}):
        try:
            report_date = dt.date.fromisoformat(str(date_key))
        except (TypeError, ValueError):
            continue
        iso = report_date.isocalendar()
        if (int(iso[0]), int(iso[1])) != (int(year), int(week)):
            continue
        entry = _teamleiter_daily_entry(data, report_date, team)
        if entry.get('checked_at') and (latest is None or report_date > latest['date']):
            latest = {'date': report_date, 'entry': entry}

    # Rückfall für bereits vorhandene Meldungen aus der alten Wochenstruktur.
    legacy_entries = data.get('checkins', {}).get(_teamleiter_week_key(year, week), {}).get(team, {}) or {}
    for day_number, day_name in ((1, 'monday'), (3, 'wednesday')):
        entry = legacy_entries.get(day_name) or {}
        if not entry.get('checked_at'):
            continue
        report_date = _teamleiter_date_for_weekday(year, week, day_number)
        if latest is None or report_date > latest['date']:
            latest = {'date': report_date, 'entry': entry}
    return latest


def _teamleiter_report_snapshot(data, year, week, team):
    """Erfasst die Teamkennzahlen zum Zeitpunkt der Tagesmeldung."""
    key = _teamleiter_week_key(year, week)
    employees = [
        employee for employee in data.get('employees', [])
        if employee.get('active', True) and employee.get('team') == team
    ]
    attendance = data.get('attendance', {}).get(key, {})
    counts = {'present': 0, 'vacation': 0, 'sick': 0}
    for employee in employees:
        status = _text(attendance.get(str(employee.get('id')), {}).get('status')).casefold()
        counter = {'anwesend': 'present', 'urlaub': 'vacation', 'krank': 'sick'}.get(status)
        if counter:
            counts[counter] += 1
    team_capacity = _teamleiter_capacity(data, year, week).get(
        team, {'gross': 0.0, 'absence': 0.0, 'available': 0.0}
    )
    return {
        'active_employees': len(employees),
        'present': counts['present'],
        'vacation': counts['vacation'],
        'sick': counts['sick'],
        'gross': team_capacity['gross'],
        'absence': team_capacity['absence'],
        'available': team_capacity['available'],
    }


def _teamleiter_master_overview(data, year, week):
    key = _teamleiter_week_key(year, week)
    attendance = data.get('attendance', {}).get(key, {})
    daily_checkins = data.get('daily_checkins', {})
    capacity = _teamleiter_capacity(data, year, week)
    current_date = datetime.now().date()
    is_current_week = _teamleiter_is_current_week(year, week)
    current_weekday = int(current_date.isocalendar()[2]) if is_current_week else 0
    monday_date = _teamleiter_date_for_weekday(year, week, 1)
    wednesday_date = _teamleiter_date_for_weekday(year, week, 3)
    monday_due = is_current_week and current_weekday >= 1
    wednesday_due = is_current_week and current_weekday >= 3
    overview = []
    totals = {
        'active_employees': 0,
        'present': 0,
        'vacation': 0,
        'sick': 0,
        'gross': 0.0,
        'absence': 0.0,
        'available': 0.0,
        'team_count': len(TEAMLEITER_TEAMS),
        'required_checkins': len(TEAMLEITER_TEAMS) * (int(monday_due) + int(wednesday_due)),
        'open_checkins': 0,
    }

    for team in TEAMLEITER_TEAMS:
        employees = [
            employee for employee in data.get('employees', [])
            if employee.get('active', True) and employee.get('team') == team
        ]
        counts = {'present': 0, 'vacation': 0, 'sick': 0}
        status_to_count = {'anwesend': 'present', 'urlaub': 'vacation', 'krank': 'sick'}
        for employee in employees:
            status = _text(attendance.get(str(employee.get('id')), {}).get('status')).casefold()
            counter = status_to_count.get(status)
            if counter:
                counts[counter] += 1

        team_capacity = capacity.get(team, {'gross': 0.0, 'absence': 0.0, 'available': 0.0})
        latest_report = _teamleiter_latest_report(data, year, week, team)
        latest_entry = latest_report['entry'] if latest_report else {}
        latest_snapshot = latest_entry.get('snapshot') if isinstance(latest_entry.get('snapshot'), dict) else {}
        latest_is_today = bool(latest_report and latest_report['date'] == current_date)
        latest_values = latest_snapshot or team_capacity

        displayed_values = {
            'active_employees': latest_values.get('active_employees', len(employees)),
            'present': latest_values.get('present', counts['present']),
            'vacation': latest_values.get('vacation', counts['vacation']),
            'sick': latest_values.get('sick', counts['sick']),
            'gross': latest_values.get('gross', team_capacity['gross']),
            'absence': latest_values.get('absence', team_capacity['absence']),
            'available': latest_values.get('available', team_capacity['available']),
        }
        row = {
            'team': team,
            **displayed_values,
            'latest_report': {
                'exists': bool(latest_report),
                'is_today': latest_is_today,
                'date': _teamleiter_daily_key(latest_report['date']) if latest_report else '',
                'checked_at': _text(latest_entry.get('checked_at')),
                'checked_by': _text(latest_entry.get('checked_by')),
                **displayed_values,
            },
        }
        overview.append(row)
        for field in ('active_employees', 'present', 'vacation', 'sick', 'gross', 'absence', 'available'):
            totals[field] += row[field]

    totals['open_checkins'] = 0
    return overview, totals


def _render_teamleiter_page(selected_team=None):
    data = _load_teamleiter_data()
    now = datetime.now().isocalendar()
    year = int(request.args.get('year', now[0]))
    week = int(request.args.get('week', now[1]))
    if selected_team and selected_team not in TEAMLEITER_TEAMS:
        return 'Unbekanntes Team', 404
    return render_template(
        'teamleiter_kapa.html',
        data=data,
        teams=TEAMLEITER_TEAMS,
        selected_team=selected_team,
        selected_year=year,
        selected_week=week,
        current_iso_year=int(now[0]),
        current_iso_week=int(now[1]),
        is_current_week=(year == int(now[0]) and week == int(now[1])),
        capacity=_teamleiter_capacity(data, year, week),
        absence_rate=int(_number(data.get('settings', {}).get('absence_rate'), TEAMLEITER_ABSENCE_RATE) * 100),
    )


@app.route('/teamleiter-master', methods=['GET'])
def teamleiter_master():
    data = _load_teamleiter_data()
    now = datetime.now().isocalendar()
    year = int(request.args.get('year', now[0]))
    week = int(request.args.get('week', now[1]))
    overview, totals = _teamleiter_master_overview(data, year, week)
    return render_template(
        'masteruebersicht.html',
        teams=TEAMLEITER_TEAMS,
        selected_year=year,
        selected_week=week,
        overview=overview,
        totals=totals,
    )


@app.route('/teamleiter-kapa', methods=['GET'])
def teamleiter_kapa():
    return _render_teamleiter_page()


@app.route('/teamleiter_kapa_m1_<team_name>', methods=['GET'])
def teamleiter_kapa_team(team_name):
    return _render_teamleiter_page(team_name)


@app.route('/api/teamleiter-kapa', methods=['GET', 'POST'])
def teamleiter_kapa_api():
    data = _load_teamleiter_data()
    if request.method == 'GET':
        year = int(request.args.get('year', datetime.now().isocalendar()[0]))
        week = int(request.args.get('week', datetime.now().isocalendar()[1]))
        return jsonify({'data': data, 'capacity': _teamleiter_capacity(data, year, week)})

    payload = request.get_json(silent=True) or {}
    action = _text(payload.get('action'))

    if action == 'save_employee':
        requested_week = _teamleiter_parse_week(payload.get('week'))
        if not requested_week or not _teamleiter_is_current_week(*requested_week):
            return jsonify({'success': False, 'error': 'Nur die aktuelle Kalenderwoche kann bearbeitet werden.'}), 403
        employee = payload.get('employee') or {}
        name = _text(employee.get('name'))
        team = _text(employee.get('team'))
        weekly_hours = _number(employee.get('weekly_hours'))
        if not name or team not in TEAMLEITER_TEAMS or weekly_hours <= 0:
            return jsonify({'success': False, 'error': 'Name, Team und Wochenstunden sind erforderlich.'}), 400
        personnel_number = _text(employee.get('personnel_number'))
        if any(
            str(item.get('personnel_number', '')) == personnel_number
            and str(item.get('id')) != _text(employee.get('id'))
            for item in data.get('employees', [])
        ):
            return jsonify({'success': False, 'error': 'Diese Personalnummer ist bereits vergeben.'}), 400
        if not personnel_number.isdigit() or int(personnel_number) <= 0:
            return jsonify({'success': False, 'error': 'Eine gültige Personalnummer ist erforderlich.'}), 400
        employee_id = _text(employee.get('id')) or personnel_number
        updated = {
            'id': employee_id,
            'personnel_number': personnel_number,
            'name': name,
            'team': team,
            'weekly_hours': weekly_hours,
            'active': bool(employee.get('active', True)),
        }
        data['employees'] = [item for item in data['employees'] if str(item.get('id')) != employee_id]
        data['employees'].append(updated)

    elif action == 'remove_employee':
        requested_week = _teamleiter_parse_week(payload.get('week'))
        if requested_week and not _teamleiter_is_current_week(*requested_week):
            return jsonify({'success': False, 'error': 'Nur die aktuelle Kalenderwoche kann bearbeitet werden.'}), 403
        employee_id = _text(payload.get('id'))
        for employee in data['employees']:
            if str(employee.get('id')) == employee_id:
                employee['active'] = False
                break

    elif action == 'save_attendance':
        employee_id = _text(payload.get('employee_id'))
        year_week = _teamleiter_parse_week(payload.get('week'))
        status = _text(payload.get('status')) or 'anwesend'
        hours = _number(payload.get('hours'))
        if not employee_id or not year_week or status not in {'anwesend', 'urlaub', 'krank'}:
            return jsonify({'success': False, 'error': 'Ungültige Anwesenheitsdaten.'}), 400
        year, week = year_week
        current_iso = datetime.now().isocalendar()
        if (year, week) != (int(current_iso[0]), int(current_iso[1])):
            return jsonify({'success': False, 'error': 'Nur die aktuelle Kalenderwoche kann bearbeitet werden.'}), 403
        key = _teamleiter_week_key(year, week)
        data['attendance'].setdefault(key, {})[employee_id] = {'status': status, 'hours': max(0.0, hours)}

    elif action == 'save_checkin':
        year_week = _teamleiter_parse_week(payload.get('week'))
        team = _text(payload.get('team'))
        checked_by = _text(payload.get('checked_by')) or _text(session.get('username')) or 'Teamleiter'
        if not year_week or team not in TEAMLEITER_TEAMS:
            return jsonify({'success': False, 'error': 'Ungültige Check-in-Daten.'}), 400
        year, week = year_week
        if not _teamleiter_is_current_week(year, week):
            return jsonify({'success': False, 'error': 'Nur die aktuelle Kalenderwoche kann bearbeitet werden.'}), 403
        day = _text(payload.get('day')).lower()
        if day not in {'monday', 'tuesday', 'wednesday', 'thursday', 'friday'}:
            return jsonify({'success': False, 'error': 'Meldung muss an einem Arbeitstag abgegeben werden.'}), 400
        today = datetime.now().date()
        weekday_names = {
            0: 'monday',
            1: 'tuesday',
            2: 'wednesday',
            3: 'thursday',
            4: 'friday',
        }
        if day != weekday_names.get(today.weekday()):
            return jsonify({'success': False, 'error': 'Die Meldung kann nur für den heutigen Arbeitstag abgegeben werden.'}), 400
        daily_key = _teamleiter_daily_key(today)
        data.setdefault('daily_checkins', {}).setdefault(daily_key, {}).setdefault(team, {})['checkin'] = {
            'checked_at': datetime.now().isoformat(timespec='minutes'),
            'checked_by': checked_by,
            'required': day in {'monday', 'wednesday'},
            'snapshot': _teamleiter_report_snapshot(data, year, week, team),
        }

    elif action == 'save_settings':
        requested_week = _teamleiter_parse_week(payload.get('week'))
        if requested_week and not _teamleiter_is_current_week(*requested_week):
            return jsonify({'success': False, 'error': 'Nur die aktuelle Kalenderwoche kann bearbeitet werden.'}), 403
        rate = _number(payload.get('absence_rate'))
        if rate > 1:
            rate /= 100.0
        data['settings']['absence_rate'] = min(max(rate, 0.0), 1.0)

    else:
        return jsonify({'success': False, 'error': 'Unbekannte Aktion.'}), 400

    _save_teamleiter_data(data)
    return jsonify({'success': True, 'data': data})


@app.route('/kapa')
def kapa():
    auftrag_info = AuftragInfo.query.all()
    gruppe = session.get('abteilung', 'E1')
    planning_weeks = get_planning_weeks(before=6, after=6)

    # Die Grenzen werden als echte datetime-Werte übergeben. Dadurch wird die
    # bisherige vertauschte Monats-/Tagesformatierung vermieden.
    first_monday = datetime.fromisocalendar(*planning_weeks[0], 1)
    last_monday = datetime.fromisocalendar(*planning_weeks[-1], 1)
    date_min = first_monday
    date_max = last_monday + timedelta(days=7)

    records = getJobs_weekly(gruppe, 20, 50, date_min, date_max)
    week_plan = build_week_plan(records, auftrag_info, planning_weeks)
    return render_template(
        'kapa.html',
        week_plan=week_plan,
        teams=TEAM_CONFIG,
        planning_weeks=planning_weeks,
        today_iso=datetime.now().date().isoformat(),
        current_iso=datetime.now().isocalendar(),
        current_year=int(datetime.now().isocalendar()[0]),
        current_week=int(datetime.now().isocalendar()[1]),
    )
