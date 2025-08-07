import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, flash, url_for
import datetime as dt
from datetime import datetime, timedelta
from collections import defaultdict
from config import connectionString
from collections import defaultdict
from sqlalchemy import asc
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


def data_MG():
    with app.app_context():
        conn = pyodbc.connect(connectionString)

        Gruppe = "E1"
        ZustandMin = "30"
        ZustandMax = "50"
        DateMin = "2024-01-01 00:00:00"
        DateMax = "2024-30-11 00:00:00"
        Typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;
        SQL_QUERY = f"""
                        SELECT 
                        FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez, FAPOS.Mng, FAPOS.StartTermPlan, FAPOS.EndTermPlan, FAPOS.PmNr, ARBPLATZ.Bez, FAPOS.Mng, FAPOS.MngGutIst, FAPOS.Zeit, FAPOS.MngRest
                        FROM 
                        INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                        WHERE
                        FAPOS.Teil = TEILE.Teil AND TEILE.Gruppe = '{Gruppe}' AND FAPOS.Zustand <= '{ZustandMax}' AND FAPOS.Zustand >= '{ZustandMin}' AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{Typ}'
                        AND FAPOS.StartTermPlan > '{DateMin}' AND FAPOS.StartTermPlan < '{DateMax}'
                        ORDER BY
                        FAPOS.StartTermPlan, FAPOS.EndTermPlan
                        """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()
        return records


def group_jobs_by_week(records):
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


def get_jobs(gruppe, masch_gruppe ,zustand_min, zustand_max, date_min, date_max):
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;
    if masch_gruppe == 0:  # Wenn keine Maschinengruppe angegeben wurde
        SQL_QUERY = f"""
                                SELECT 
                                FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez, FAPOS.Mng, FAPOS.StartTermPlan,
                                FAPOS.EndTermPlan, FAPOS.PmNr, FAPOS.Mng, FAPOS.MngRest, FAPOS.Zeit, FAPOS.Pos,
                                FAPOS.ZeitIst, FAPOS.Bez AS posbez, ARBPLATZ.Bez AS ArbBez
                                FROM 
                                INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                                WHERE
                                FAPOS.Teil = TEILE.Teil AND TEILE.Gruppe = '{gruppe}' AND FAPOS.Zustand <= '{zustand_max}' AND FAPOS.Zustand >= '{zustand_min}' AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{typ}'
                                AND FAPOS.StartTermPlan > '{date_min}' AND FAPOS.StartTermPlan < '{date_max}'
                                AND NOT (FAPOS.Stat = 'E' AND (FAPOS.Zustand = '10' OR FAPOS.Zustand = '20'))
                                ORDER BY
                                FAPOS.StartTermPlan, FAPOS.EndTermPlan, FAPOS.Pos
                                """
    else:   # Nach Maschinengruppe filtern
        SQL_QUERY = f"""
                                SELECT 
                                FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez, FAPOS.Mng, FAPOS.StartTermPlan,
                                FAPOS.EndTermPlan, FAPOS.PmNr, FAPOS.Mng, FAPOS.MngRest, FAPOS.Zeit, FAPOS.Pos,
                                FAPOS.ZeitIst, FAPOS.Bez AS posbez, ARBPLATZ.Bez AS ArbBez
                                FROM 
                                INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                                WHERE
                                FAPOS.Teil = TEILE.Teil AND TEILE.Gruppe = '{gruppe}' AND FAPOS.Zustand <= '{zustand_max}' AND FAPOS.Zustand >= '{zustand_min}' AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{typ}'
                                AND FAPOS.StartTermPlan > '{date_min}' AND FAPOS.StartTermPlan < '{date_max}' AND FAPOS.PmNr = '{masch_gruppe}'
                                AND NOT (FAPOS.Stat = 'E' AND (FAPOS.Zustand = '10' OR FAPOS.Zustand = '20'))
                                ORDER BY
                                FAPOS.StartTermPlan, FAPOS.EndTermPlan, FAPOS.Pos
                                """
    cursor = conn.cursor()
    cursor.execute(SQL_QUERY)
    records = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    jobs = [dict(zip(columns, row)) for row in records]
    return jobs


def get_mat_buchungen(Buchungsdatum_min, Buchungsdatum_max, Erfassende, Teilegruppe, Buchungsart):
    with app.app_context():
        conn = pyodbc.connect(connectionString)

        # Basis-SQL-Abfrage ohne Erfassende- und Teilegruppen-Filter
        SQL_QUERY = f"""
            SELECT 
                DATEPART(WEEK, BEWEGUNG.AendDat) AS Kalenderwoche,
                BEWEGUNG.Lag,
                SUM(BEWEGUNG.MngEff) AS Summe_Menge,
                TEILE.Gruppe
            FROM 
                INFRADB.dbo.BEWEGUNG BEWEGUNG
            INNER JOIN 
                INFRADB.dbo.TEILE TEILE ON BEWEGUNG.Teil = TEILE.Teil
            WHERE
                BEWEGUNG.AendDat > '{Buchungsdatum_min}'
                AND BEWEGUNG.AendDat < '{Buchungsdatum_max}'
                AND BEWEGUNG.BuchArt = '{Buchungsart}'
                AND BEWEGUNG.Lag IN ('A', 'E')
        """

        # Füge den Erfassende-Filter nur hinzu, wenn Erfassende nicht leer ist
        if Erfassende:
            SQL_QUERY += f" AND BEWEGUNG.SbErf IN ({', '.join(f"'{e}'" for e in Erfassende)})"

        # Füge den Teilegruppen-Filter nur hinzu, wenn Teilegruppe nicht leer ist
        if Teilegruppe:
            SQL_QUERY += f" AND TEILE.Gruppe = '{Teilegruppe}'"

        # Schließe die GROUP BY und ORDER BY-Klauseln an
        SQL_QUERY += """
            GROUP BY 
                DATEPART(WEEK, BEWEGUNG.AendDat), BEWEGUNG.Lag, TEILE.Gruppe
            ORDER BY 
                Kalenderwoche, BEWEGUNG.Lag
        """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        mat_buchungen = cursor.fetchall()
        return mat_buchungen


def get_job_ahead(jobs):
    conn = pyodbc.connect(connectionString)  # Ensure connection is defined
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;

    for job in jobs:
        auftrag = job['Auftrag']
        pos = job['Pos']

        SQL_QUERY = """
            SELECT TOP 1 
                FAPOS.Zustand, 
                ARBPLATZ.Bez, 
                FAPOS.Pos
            FROM 
                INFRADB.dbo.FAPOS AS FAPOS
            JOIN 
                INFRADB.dbo.TEILE AS TEILE ON FAPOS.Teil = TEILE.Teil
            JOIN 
                INFRADB.dbo.ARBPLATZ AS ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
            WHERE 
                FAPOS.Typ = ? 
                AND FAPOS.Auftrag = ? 
                AND FAPOS.Pos < ? 
            ORDER BY 
                FAPOS.Pos DESC  -- Gets the closest smaller Pos
        """

        with conn.cursor() as cursor:
            cursor.execute(SQL_QUERY, (typ, auftrag, pos))
            record = cursor.fetchone()

            if record:
                job['job_ahead'] = record[1][:3]  # First 3 chars of ARBPLATZ.Bez
                job['job_ahead_zustand'] = record[0]  # Zustand

    conn.close()
    return jobs


def get_delay(jobs):
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;

    for job in jobs:
        auftrag = job['Auftrag']
        pos = job['Pos']

        SQL_QUERY = f"""
            SELECT 
                FAPOS.Auftrag, FAPOS.StartTermPlan
            FROM 
                INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
            WHERE
                FAPOS.Teil = TEILE.Teil 
                AND FAPOS.PmNr = ARBPLATZ.PmNr 
                AND FAPOS.Typ = '{typ}' 
                AND FAPOS.Auftrag = '{auftrag}'
                AND FAPOS.Pos = {pos}
            ORDER BY
                FAPOS.Pos
        """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()

        delays = []
        for r in records:
            start_date = r[1].date()
            today = dt.datetime.today().date()
            delay = (start_date - today).days
            delays.append(delay)

        if delays:
            job['delay'] = min(delays)  # z.B. minimaler delay
        else:
            job['delay'] = None  # oder z.B. 0 oder ein sinnvoller Default-Wert

    return jobs


def get_kw_workload(grouped_jobs):
    team = Personal.query.all()
    stunden = StundenKW.query.all()
    l = ['2410-01', '2410-50', '2410-03', '2410-04', '2450-01']
    workload = {}  # Dictionary, um Ergebnisse zu speichern

    # ---> Berechnung IST-Stunden
    for AG in l:
        for std in stunden:
            # Prüfen, ob die Person der Gruppe AG angehört
            person = next((pers for pers in team if pers.pers_nr == std.pers_nr and pers.gruppe == AG), None)

            if person:
                # Schlüssel für Jahr und KW erstellen
                key = (std.jahr, std.kw, AG)
                if key not in workload:
                    # Initialisieren mit einem Dictionary für 'h_ist' und 'h_plan'
                    workload[key] = {'h_ist': 0, 'h_plan': 0}
                # Stunden summieren
                workload[key]['h_ist'] += float(std.stunden_kw)  # Konvertierung zu float

    # ---> Berechnung PLAN-Stunden
    for (year, week), jobs in grouped_jobs.items():
        for job in jobs:
            for AG in l:
                if job.get('PmNr') == AG:
                    # Schlüssel für Jahr, KW und Gruppe erstellen
                    key = (year, week, AG)
                    if key not in workload:
                        # Initialisieren mit einem Dictionary für 'h_ist' und 'h_plan'
                        workload[key] = {'h_ist': 0, 'h_plan': 0}
                    # Planzeit aus Job summieren
                    workload[key]['h_plan'] += float(job.get('Zeit', 0))  # Konvertierung zu float

    # ---> Ergebnisse in die WorkLoad-Tabelle schreiben oder aktualisieren
    for (jahr, kw, AG), hours in workload.items():
        h_ist = hours['h_ist']  # Konvertierung zu float
        h_plan = round(float(hours['h_plan']/60),1)  # Konvertierung zu float

        # Prüfen, ob ein Eintrag für diese Kombination bereits existiert
        existing_entry = WorkLoad.query.filter_by(year=jahr, kw=kw, gruppe=AG).first()

        if existing_entry:
            # Vorhandenen Eintrag aktualisieren
            existing_entry.h_ist = h_ist
            existing_entry.h_plan = h_plan
        else:
            # Neuen Eintrag erstellen
            workload_entry = WorkLoad(
                year=jahr,
                kw=kw,
                gruppe=AG,
                h_ist=h_ist,
                h_plan=h_plan
            )
            db.session.add(workload_entry)

    db.session.commit()

    return ()


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
    grouped_jobs = group_jobs_by_week(records)


    return render_template('index.html',grouped_jobs=grouped_jobs
                           , workload=workload, stunden=stunden, team=team, auftrag_info=auftrag_info)


@app.route('/programmierliste', methods=['GET', 'POST'])
def programmierliste():
    if request.method == 'POST':

        #Bezeichnung, Index und KND aus Infra
        GreiplNr = request.form['GNR']
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
                                           SELECT 
                                           TEILE.Bez, TEILE.AendIxSL, KUNDE.Bez, FKOPF.StartTerm
                                           FROM 
                                           INFRADB.dbo.TEILE TEILE, INFRADB.dbo.FKOPF FKOPF, INFRADB.dbo.KUNDE KUNDE 
                                           WHERE
                                           TEILE.Teil = '{GreiplNr}' AND TEILE.Teil = FKOPF.Teil AND FKOPF.Knd = KUNDE.Knd
                                           """

        with pyodbc.connect(connectionString) as conn:
            cursor = conn.cursor()
            cursor.execute(SQL_QUERY)
            record = cursor.fetchone()
            if record and len(record) >= 3:
                InfraBez = record[0]
                InfraRev = record[1]
                InfraKnd = record[2]
                print(str(record[3]))
            else:
                print("Keine gültigen Daten aus der Datenbank.")
                return 0

        new_task = ProgrammierListe(
            TYP=request.form['TYP'],
            GNR=request.form['GNR'],
            BEZ=InfraBez,
            REV=InfraRev,
            KND=InfraKnd,
            COM=request.form['COM'],
            PFAD=request.form['PFAD'],
        )
        db.session.add(new_task)
        db.session.commit()
        return redirect(url_for('programmierliste'))
    else:
        tasks = ProgrammierListe.query.all()
        update_fa_start_from_infra()
        return render_template('programmierliste.html', tasks=tasks)

def update_fa_start_from_infra():
    open_tasks = ProgrammierListe.query.filter_by(Done=False).all()
    updated_count = 0

    with pyodbc.connect(connectionString) as conn:
        cursor = conn.cursor()

        for task in open_tasks:
            greipl_nr = task.GNR

            cursor.execute("""
                SELECT TOP 1 StartTerm
                FROM INFRADB.dbo.FKOPF
                WHERE Teil = ?
                  AND StartTerm >= GETDATE()
                  AND Zustand < 40
                ORDER BY StartTerm ASC
            """, (greipl_nr,))

            record = cursor.fetchone()
            if record and record[0]:
                try:
                    start_term = record[0].strftime('%d.%m.%y')
                except AttributeError:
                    start_term = str(record[0])

                task.FA_start = start_term
                updated_count += 1

        db.session.commit()

    print(f"{updated_count} Einträge wurden mit dem nächsten zukünftigen FA_start aktualisiert.")

@app.route('/update_comment_prog/<int:task_id>', methods=['POST'])
def update_comment_prog(task_id):
    data = request.get_json()
    comment = data.get('comment', '')
    task = ProgrammierListe.query.get(task_id)
    if task:
        task.COM = comment
        db.session.commit()
        return jsonify({'success': True}), 200
    return jsonify({'error': 'Task not found'}), 404


@app.route('/update_status/<int:task_id>', methods=['POST'])
def update_status(task_id):
    data = request.get_json()
    field = data.get('field')
    value = data.get('value')

    task = ProgrammierListe.query.get(task_id)
    if not task:
        return jsonify({'error': 'Task nicht gefunden'}), 404

    if field not in ['DAT', 'SMT', 'AOI', 'AA', 'STC', 'THT']:
        return jsonify({'error': 'Ungültiges Feld'}), 400

    # Feld aktualisieren
    setattr(task, field, value)

    # Prüfen, ob alle Felder auf 'Erledigt' oder 'Nicht benötigt' stehen
    fields = [task.DAT, task.SMT, task.STC, task.AOI, task.THT, task.AA]
    task.Done = all(f in ["Erledigt", "nb"] for f in fields)

    # Wenn Done True ist, setze das aktuelle Datum + Uhrzeit im gewünschten Format
    if task.Done:
        task.Done_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    else:
        # Optional: Wenn nicht erledigt, das Datum zurücksetzen (kannst du weglassen, wenn nicht gewünscht)
        task.Done_date = None

    db.session.commit()
    return jsonify({'success': True, 'done': task.Done})


@app.route('/delete_task/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    task = ProgrammierListe.query.get(task_id)
    if not task:
        return jsonify({'error': 'Nicht gefunden'}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})


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


@app.route('/personal/add', methods=['POST'])
def personal_add():

    pers_nr = request.form.get('pers_nr')
    gruppe = request.form.get('gruppe')
    name = request.form.get('name')
    vorname = request.form.get('vorname')
    stunden_tag = request.form.get('stunden_tag')
    tage_woche = request.form.get('tage_woche')

    new_personal = Personal(
        pers_nr=pers_nr,
        gruppe=gruppe,
        name=name,
        vorname=vorname,
        stunden_tag=stunden_tag,
        tage_woche=tage_woche
    )

    db.session.add(new_personal)
    db.session.commit()
    return redirect('/personal')


@app.route('/update_stunden_korr', methods=['POST'])
def update_stunden_korr():
    stunden = StundenKW.query.all()

    for st in stunden:
        # Hole den neuen Korrekturwert für jedes stunden_korr-Feld
        stunden_korr_value = request.form.get(f'stunden_korr_{st.id}')
        stunden_korr_bemerk = request.form.get(f'korr_bemerk_{st.id}')
        if stunden_korr_value:
            # Aktualisiere den stunden_korr-Wert in der Datenbank
            st.stunden_korr = int(stunden_korr_value)  # Umwandlung des Werts in eine Ganzzahl
            db.session.commit()  # Änderungen in der Datenbank speichern
        if stunden_korr_value:
            # Aktualisiere den stunden_korr-Wert in der Datenbank
            st.korr_bemerk = stunden_korr_bemerk
            db.session.commit()  # Änderungen in der Datenbank speichern

    return redirect('/personal')  # Nach dem Speichern zurück zur Ansicht


@app.route('/vorrat')
def vorrat():
    auftrag_info = AuftragInfo.query.all()
    gruppe = "E1"
    zustand_min = "20"
    zustand_max = "50"
    date_min = "2010-01-01 00:00:00"
    date_max = "2099-31-12 00:00:00"

    masch_gruppe = "2410-01"  # SMT
    smd_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(smd_jobs)
    get_delay(smd_jobs)

    masch_gruppe = "2410-03"  # THT
    tht_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(tht_jobs)
    get_delay(tht_jobs)

    masch_gruppe = "2410-04"  # Manuelle Handarbeit
    man_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(man_jobs)
    get_delay(man_jobs)

    masch_gruppe = "2410-50"  # 3DAOI Nacharbeit
    aoi_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(aoi_jobs)
    get_delay(aoi_jobs)

    masch_gruppe = "2450-01"  # Prüfung E1
    pruef_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(pruef_jobs)
    get_delay(pruef_jobs)

    return render_template('vorrat.html', smd_jobs=smd_jobs, tht_jobs=tht_jobs, man_jobs=man_jobs, pruef_jobs=pruef_jobs, aoi_jobs=aoi_jobs,auftrag_info=auftrag_info)


@app.route('/kpi')
def kpi():
## Auftragskennzahlen
# Status Aufträge nach KW
    # Auftragsdaten abrufen
    Aufträge = data_FA("E1", "10", "60", "2025-01-01 00:00:00", "2025-31-12 00:00:00", "E")
    print(Aufträge)

    # Dictionary zur Speicherung der Anzahl der Aufträge nach Kalenderwoche und Status
    fa_wochenweise = {}

    for row in Aufträge:
        kalenderwoche = row[-1]  # Kalenderwoche is now the last column
        status = int(row[0])  # Status is the first column (FAPOS.Zustand)

        # Überprüfen, ob die Kalenderwoche bereits im Dictionary existiert
        if kalenderwoche not in fa_wochenweise:
            # Initialisieren des Dictionaries mit allen möglichen Statuswerten (10, 20, 30, 40, 50, 60)
            fa_wochenweise[kalenderwoche] = {10: 0, 20: 0, 30: 0, 40: 0, 50: 0, 60: 0}

        # Erhöhen der Zählung für den entsprechenden Status
        if status in fa_wochenweise[kalenderwoche]:
            fa_wochenweise[kalenderwoche][status] += 1

    print(fa_wochenweise)

#  Fertigmeldungen Aufträge nach Jahre

    current_date = dt.date.today()
    aktuelles_jahr = int(current_date.strftime("%Y"))
    fa_fertig_jahr = {}
    for jahr in range(aktuelles_jahr-5, aktuelles_jahr+1):
        sum = 0
        fa_fertig = get_mat_buchungen(str(jahr) + "-01-01 00:00:00", str(jahr) + "-31-12 00:00:00", "", "E1", "ZF")  # ZF = fertigmeldung
        for row in fa_fertig:
            sum += row[2]
        print(str(jahr) + " Menge: " + str(sum))
        if jahr not in fa_fertig_jahr:
            fa_fertig_jahr[jahr] = 0.0
        fa_fertig_jahr[jahr] = sum
    print(fa_fertig_jahr)


#  Fertigmeldungen Aufträge nach KW
    fa_fertig = get_mat_buchungen("2025-01-01 00:00:00", "2100-01-01 00:00:00", "", "E1", "ZF")  # ZF = fertigmeldung
    fa_fertig_wochenweise = {}
    for row in fa_fertig:
        kalenderwoche = row[0]
        lager = row[1]
        menge = float(row[2])  # ← Hier konvertieren wir Decimal zu float

        if kalenderwoche not in fa_fertig_wochenweise:
            fa_fertig_wochenweise[kalenderwoche] = 0.0
        fa_fertig_wochenweise[kalenderwoche] += menge
        print(fa_fertig_wochenweise)

## Materialwirtschaft
#  Meterialmengen
    mat_buchungen = get_mat_buchungen("2025-01-01 00:00:00", "2100-01-01 00:00:00", ["mranz", "teder", "jbusc", "julli"], "", "AR")  # AR = Metrialentnahme
    buchungen_wochenweise = {}
    for row in mat_buchungen:
        kalenderwoche = row[0]
        lager = row[1]
        menge = float(row[2])  # ← Hier konvertieren wir Decimal zu float

        if kalenderwoche not in buchungen_wochenweise:
            buchungen_wochenweise[kalenderwoche] = {"A": 0, "E": 0}

        buchungen_wochenweise[kalenderwoche][lager] += menge

    return render_template('kpi.html', buchungen_wochenweise=buchungen_wochenweise, fa_wochenweise=fa_wochenweise, fa_fertig_wochenweise=fa_fertig_wochenweise, fa_fertig_jahr=fa_fertig_jahr)


@app.route('/settings')
def settings():

    return render_template('settings.html')


@app.route('/tools')
def tools():

    return render_template('tools.html')


@app.route('/grafik')
def grafik():

    gruppe = "E1"
    zustand_min = "10"
    zustand_max = "60"
    date_min = (datetime.now() - timedelta(weeks=6)).strftime("%Y-%d-%m %H:%M:%S")
    date_max = "2099-30-12 00:00:00"
    masch_gruppe = 0

    jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)  # Arbeitsgänge auslesen
    grouped_jobs = group_by_calendar_week(jobs)  # Gruppieren der Arbeitsgänge nach KW
    #  print(grouped_jobs)

    get_kw_workload(grouped_jobs)  # Summieren der Arbeitsgang-Zeiten nach Gruppe und KW

    return render_template('index.html', jobs=jobs, grouped_jobs=grouped_jobs)


@app.route('/tempcheck', methods=['GET', 'POST'])
def tempcheck():
    if request.method == 'POST':
        # Sicherstellen, dass die Datei vorhanden ist
        if 'file' not in request.files:
            flash('Keine Datei hochgeladen!', 'error')
            return redirect(request.url)

        # Datei aus der Anfrage laden
        file = request.files['file']

        # Validierung der Dateiendung (optional)
        if not file.filename.endswith('.csv'):
            flash('Nur CSV-Dateien werden unterstützt!', 'error')
            return redirect(request.url)

        # Speichern der Datei auf dem Server
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        try:
            file.save(file_path)
            flash(f'Datei erfolgreich hochgeladen: {file.filename}', 'success')
        except Exception as e:
            flash(f'Fehler beim Speichern der Datei: {e}', 'error')
            return redirect(request.url)

        return redirect(url_for('tempcheck'))

    return render_template('tempcheck.html')


def adjust_time_to_50C(timestamps, temperatures):
    """ Setzt die Zeitachse auf 0 beim ersten Erreichen von 50°C. """
    # Find the first occurrence of >= 50°C
    for i, temp in enumerate(temperatures):
        if temp >= 50.0:
            start_index = i
            break
    else:
        return timestamps, temperatures  # Keine 50°C gefunden

    # Der Start-Zeitstempel, bei dem 50°C erreicht wird
    start_timestamp = float(timestamps[start_index])

    # Alle Zeitstempel anpassen (nur die X-Achse verschieben)
    adjusted_timestamps = [float(t) - start_timestamp for t in timestamps[start_index:]]

    return adjusted_timestamps, temperatures[start_index:]


@app.route('/tempcheck/files', methods=['GET', 'POST'])
def get_available_files():
    try:
        # Listet alle CSV-Dateien im Upload-Ordner auf
        files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if f.endswith('.csv')]
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': f'Fehler beim Laden der Dateien: {str(e)}'}), 500


@app.route('/tempcheck/render', methods=['GET', 'POST'])
def render_tempcheck_data():
    if request.method == 'GET':
        main_file_name = request.args.get('file')
    elif request.method == 'POST':
        # Prüfe, ob Datei-Upload oder nur Dateiname
        if 'file' in request.form:
            main_file_name = request.form.get('file')
        elif request.is_json:
            data = request.get_json(silent=True)
            main_file_name = data.get('file') if data else None
        elif 'file' in request.files:
            uploaded_file = request.files['file']
            main_file_name = uploaded_file.filename
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], main_file_name)
            uploaded_file.save(save_path)
        else:
            main_file_name = None

    if not main_file_name:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], main_file_name)

    temperatures = []
    timestamps = []
    max_temperatures = []
    min_temperatures = []

    try:
        # Hauptdatei einlesen
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            csvreader = csv.reader(csvfile, delimiter=';')
            next(csvreader)  # Kopfzeile überspringen
            for row in csvreader:
                timestamp_value = row[0].replace(',', '.')
                temp_value = row[1].replace(',', '.')
                timestamps.append(timestamp_value)
                temperatures.append(float(temp_value))

        # Max-Temperaturdatei einlesen
        max_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'JEDEC_temp_max.csv')
        if os.path.exists(max_file_path):
            with open(max_file_path, newline='', encoding='utf-8') as csvfile:
                csvreader = csv.reader(csvfile, delimiter=';')
                next(csvreader)
                for row in csvreader:
                    max_temp_value = row[1].replace(',', '.')
                    max_temperatures.append(float(max_temp_value))
        else:
            max_temperatures = [None] * len(timestamps)

        # Min-Temperaturdatei einlesen
        min_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'JEDEC_temp_min.csv')
        if os.path.exists(min_file_path):
            with open(min_file_path, newline='', encoding='utf-8') as csvfile:
                csvreader = csv.reader(csvfile, delimiter=';')
                next(csvreader)
                for row in csvreader:
                    min_temp_value = row[1].replace(',', '.')
                    min_temperatures.append(float(min_temp_value))
        else:
            min_temperatures = [None] * len(timestamps)

    except Exception as e:
        return jsonify({'error': f'Fehler beim Laden der Daten: {str(e)}'}), 500

    # Zeit und Temperaturen der Hauptkurve anpassen
    adjusted_timestamps, adjusted_temperatures = adjust_time_to_50C(timestamps, temperatures)

    # Max-/Min-Zeitachsen ebenso verschieben
    adjusted_max_timestamps, _ = adjust_time_to_50C(timestamps, max_temperatures)
    adjusted_min_timestamps, _ = adjust_time_to_50C(timestamps, min_temperatures)

    # Schneide Min-/Max-Werte passend auf gleiche Länge wie adjusted_x
    max_offset = len(temperatures) - len(adjusted_max_timestamps)
    min_offset = len(temperatures) - len(adjusted_min_timestamps)

    return jsonify({
        'file_name': main_file_name,
        'timestamps': adjusted_timestamps,
        'temperatures': adjusted_temperatures,
        'max_temperatures': max_temperatures[max_offset:] if max_temperatures else [],
        'max_timestamps': adjusted_max_timestamps,
        'min_temperatures': min_temperatures[min_offset:] if min_temperatures else [],
        'min_timestamps': adjusted_min_timestamps
    })


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    with app.app_context():  # Erstellt einen Anwendungscontext
        db.create_all()  # Erstellt die Datenbanktabellen
    app.run(host="0.0.0.0", port=5000, debug=True)
