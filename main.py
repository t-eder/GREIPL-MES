import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo
import json
from flask import render_template, redirect, request, Flask, render_template, jsonify
import datetime as dt
from datetime import datetime, timedelta
from collections import defaultdict
from config import connectionString
from sqlalchemy import asc

def data_FA(Gruppe, ZustandMin, ZustandMax, DateMin, DateMax, Typ):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
                               SELECT 
                                   FAPOS.Zustand, 
                                   FAPOS.Auftrag, 
                                   FAPOS.Mng, 
                                   FAPOS.StartTermPlan, 
                                   ARBPLATZ.Bez, 
                                   FAPOS.Mng, 
                                   FAPOS.MngGutIst,
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


def group_by_calendar_week(jobs):
    from datetime import datetime

    grouped_jobs = defaultdict(list)

    for job in jobs:
        # Ensure StartTermPlan is a datetime object
        start_term_plan = job.get("StartTermPlan")
        if isinstance(start_term_plan, str):
            try:
                job_date = datetime.strptime(start_term_plan, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError(f"Invalid date format for StartTermPlan: {start_term_plan}")
        elif isinstance(start_term_plan, (datetime, dt.date)):
            job_date = start_term_plan
        else:
            raise ValueError(f"Invalid type for StartTermPlan: {type(start_term_plan)}")

        # Get year and week number
        year, week, _ = job_date.isocalendar()
        grouped_jobs[(year, week)].append(job)

    return grouped_jobs


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
        # print(auftrag, pos)
        SQL_QUERY = f"""
                                    SELECT 
                                    FAPOS.Auftrag, FAPOS.StartTermPlan
                                    FROM 
                                    INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                                    WHERE
                                    FAPOS.Teil = TEILE.Teil AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{typ}' AND FAPOS.Auftrag = '{auftrag}'
                                    ORDER BY
                                    FAPOS.Pos
                                    """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()
        # print(records)

        for r in records:
            delay = (r[1] - dt.datetime.today()).days
            # print(delay)
            job['delay'] = delay
            # print(job)
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
    masch_gruppe = 0

    jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)  # Arbeitsgänge auslesen
    grouped_jobs = group_by_calendar_week(jobs)  # Gruppieren der Arbeitsgänge nach KW
    get_kw_workload(grouped_jobs)  # Summieren der Arbeitsgang-Zeiten nach Gruppe und KW

    return render_template('index.html', jobs=jobs, grouped_jobs=grouped_jobs, workload=workload, stunden=stunden, team=team, auftrag_info=auftrag_info)


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


@app.route('/personal')
def personal():
    team = Personal.query.all()
    for jahr in range(2024, 2026):
        for kw in range(1, 52):
            for pers in team:
                stunden_eintrag = StundenKW.query.filter_by(pers_nr=pers.pers_nr, jahr=jahr, kw=kw).first()
                h_kw = pers.stunden_tag * pers.tage_woche
                if stunden_eintrag:
                    # Wenn ein Eintrag existiert, korrigierte Stunden berechnen
                    stunden_eintrag.stunden_kw = h_kw - stunden_eintrag.stunden_korr
                else:
                    # Neuen Eintrag erstellen, falls keiner existiert
                    neuer_eintrag = StundenKW(
                        pers_nr=pers.pers_nr,
                        jahr=jahr,
                        kw=kw,
                        stunden_kw=h_kw,  # Anfangswert ohne Korrektur
                        stunden_korr=0  # Keine Korrektur für neuen Eintrag
                    )
                    db.session.add(neuer_eintrag)
    db.session.commit()
    stunden = StundenKW.query.order_by(asc(StundenKW.jahr), asc(StundenKW.kw), asc(StundenKW.pers_nr)).all()
    return render_template('personal.html', team=team, stunden=stunden)


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
    gruppe = "E1"
    zustand_min = "30"
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

    return render_template('vorrat.html', smd_jobs=smd_jobs, tht_jobs=tht_jobs, man_jobs=man_jobs, pruef_jobs=pruef_jobs, aoi_jobs=aoi_jobs)


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


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    with app.app_context():  # Erstellt einen Anwendungscontext
        db.create_all()  # Erstellt die Datenbanktabellen
    app.run(host="0.0.0.0", port=5000, debug=True)



