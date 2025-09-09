import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, flash, url_for
import datetime as dt
from datetime import datetime, timedelta
from config import connectionString
from collections import defaultdict
import os
import csv




def data_FA(Gruppe, ZustandMin, ZustandMax, DateMin, DateMax, Typ):
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
                AND FAPOS.Typ = '{Typ}'
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


@app.route('/update_comment', methods=['POST'])
def update_comment():
    data = request.get_json()
    fa_nr = data.get('fa_nr')
    comment = data.get('comment')
    fa_mat = data.get('fa_mat', 0)  # Checkbox Material (1 oder 0)

    if not fa_nr:
        return jsonify({'success': False, 'message': 'Keine FA-Nummer übermittelt'}), 400

    auftraginfo = AuftragInfo.query.get(fa_nr)

    if not auftraginfo:
        auftraginfo = AuftragInfo(fa_nr=fa_nr)

    # Felder aktualisieren
    auftraginfo.fa_bemerk = comment
    auftraginfo.fa_mat = fa_mat

    try:
        db.session.add(auftraginfo)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/')
def index():
    team = Personal.query.all()
    stunden = StundenKW.query.all()
    workload = WorkLoad.query.all()
    auftrag_info = AuftragInfo.query.all()

    gruppe = "E1"
    zustand_min = "10"
    zustand_max = "60"
    date_min = (datetime.now() - timedelta(weeks=6)).strftime("%Y-%d-%m %H:%M:%S")
    date_max = "2099-30-12 00:00:00"

    # masch_gruppe = 0
    # jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max) #Arbeitsgänge auslesen
    ##  print(grouped_jobs)
    # get_kw_workload(grouped_jobs)  # Summieren der Arbeitsgang-Zeiten nach Gruppe und KW

    records = data_FA(gruppe, zustand_min, zustand_max, date_min, date_max, "E")
    # print(records)
    grouped_jobs = group_FA_by_week(records)


    return render_template('index.html',grouped_jobs=grouped_jobs
                           , workload=workload, stunden=stunden, team=team, auftrag_info=auftrag_info)