import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, session
import datetime as dt
from datetime import datetime
from config import connectionString
import re

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

def get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max):
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


@app.route('/vorrat')
def vorrat():
    gruppe = session.get('abteilung', 'E1')  # z.B. 'E1', 'M1', 'M4'

    zustand_min = "20"
    zustand_max = "50"
    date_min = "2010-01-01 00:00:00"
    date_max = "2099-12-31 00:00:00"
    typ = "A"

    # Verbindung herstellen
    conn = pyodbc.connect(connectionString)
    cursor = conn.cursor()
    if gruppe == "QS":
        # --- Dynamisch alle Maschinengruppen für die Abteilung abfragen ---
        SQL_MG = f"""
            SELECT DISTINCT FAPOS.PmNr, ARBPLATZ.Bez
            FROM INFRADB.dbo.FAPOS FAPOS
            JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
            JOIN INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
            WHERE (TEILE.Gruppe IS NOT NULL)
              AND FAPOS.Typ = '{typ}'
              AND FAPOS.Zustand BETWEEN '{zustand_min}' AND '{zustand_max}'
              AND TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) IS NOT NULL
              AND NOT (FAPOS.Stat = 'E' AND FAPOS.Zustand IN ('10','20'))
            ORDER BY FAPOS.PmNr
        """
        cursor.execute(SQL_MG)
        maschinen = cursor.fetchall()
        print(f"QS liefert {len(maschinen)} Maschinengruppen")
    else:
         # --- Dynamisch alle Maschinengruppen für die Abteilung abfragen ---
        SQL_MG = f"""
            SELECT DISTINCT FAPOS.PmNr, ARBPLATZ.Bez
            FROM INFRADB.dbo.FAPOS FAPOS
            JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
            JOIN INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
            WHERE TEILE.Gruppe = '{gruppe}'
              AND FAPOS.Typ = '{typ}'
              AND FAPOS.Zustand BETWEEN '{zustand_min}' AND '{zustand_max}'
              AND TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) IS NOT NULL
              AND NOT (FAPOS.Stat = 'E' AND FAPOS.Zustand IN ('10','20'))
            ORDER BY FAPOS.PmNr
        """
        cursor.execute(SQL_MG)
        maschinen = cursor.fetchall()


# Blacklist: diese Maschinengruppen sollen ignoriert werden
# blacklist = {"A159", "A155", "A154", "A156", "8700-10", "8700-11"}
                #NZ       #NZ     #NZ    #NZ      #EMPB      #EMPB

    if gruppe == "M1":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("2440")  # beginnt mit 2440
        ]
    elif gruppe == "E1":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("2410")  # beginnt mit 2440
        ]
    elif gruppe == "M2":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("1")  # beginnt mit 2440
        ]
    elif gruppe == "M4":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("2440")  # beginnt mit 2440
               or str(row[0]).startswith("2460")  # beginnt mit 2460
        ]
    elif gruppe == "WZ":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("3")
        ]
    elif gruppe == "QS":
        # Maschinengruppenliste erstellen:
        # 1 Nicht in Blacklist
        # 2 Beginnt mit "2440"
        gruppen_liste = [
            {"pmnr": row[0], "bez": row[1]}
            for row in maschinen
            if row[0]  # nicht leer
               # and row[0] not in blacklist  # nicht in Blacklist
               and str(row[0]).startswith("8")
               or str(row[0]).startswith("2450")
        ]


    gruppen_jobs = {}
    for mg in gruppen_liste:
        pmnr = mg["pmnr"]


        if gruppe == 'QS':
            SQL_JOBS = f"""
                            SELECT 
                                FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez,
                                FAPOS.Mng, 
                                TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) AS StartTermPlan,
                                TRY_CONVERT(datetime, FAPOS.EndTermPlan, 120) AS EndTermPlan,
                                FAPOS.PmNr, FAPOS.MngRest, FAPOS.Zeit, FAPOS.Pos,
                                FAPOS.ZeitIst, FAPOS.Bez AS posbez, ARBPLATZ.Bez AS ArbBez
                            FROM INFRADB.dbo.FAPOS FAPOS
                            JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
                            JOIN INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
                            WHERE (TEILE.Gruppe IS NOT NULL)
                              AND FAPOS.Typ = '{typ}'
                              AND FAPOS.PmNr = '{pmnr}'
                              AND FAPOS.Zustand BETWEEN '{zustand_min}' AND '{zustand_max}'
                              AND TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) IS NOT NULL
                              AND NOT (FAPOS.Stat = 'E' AND FAPOS.Zustand IN ('10','20'))
                            ORDER BY StartTermPlan, EndTermPlan, Pos
                        """
        else:
            # --- Jobs je Maschinengruppe abrufen ---
            SQL_JOBS = f"""
                SELECT 
                    FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez,
                    FAPOS.Mng, 
                    TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) AS StartTermPlan,
                    TRY_CONVERT(datetime, FAPOS.EndTermPlan, 120) AS EndTermPlan,
                    FAPOS.PmNr, FAPOS.MngRest, FAPOS.Zeit, FAPOS.Pos,
                    FAPOS.ZeitIst, FAPOS.Bez AS posbez, ARBPLATZ.Bez AS ArbBez
                FROM INFRADB.dbo.FAPOS FAPOS
                JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
                JOIN INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
                WHERE TEILE.Gruppe = '{gruppe}'
                  AND FAPOS.Typ = '{typ}'
                  AND FAPOS.PmNr = '{pmnr}'
                  AND FAPOS.Zustand BETWEEN '{zustand_min}' AND '{zustand_max}'
                  AND TRY_CONVERT(datetime, FAPOS.StartTermPlan, 120) IS NOT NULL
                  AND NOT (FAPOS.Stat = 'E' AND FAPOS.Zustand IN ('10','20'))
                ORDER BY StartTermPlan, EndTermPlan, Pos
            """

        cursor.execute(SQL_JOBS)
        records = cursor.fetchall()
        columns = [c[0] for c in cursor.description]
        jobs = [dict(zip(columns, row)) for row in records]

        # --- Berechnungen ---
        get_job_ahead(jobs)
        get_delay(jobs)

        gruppen_jobs[pmnr] = {"bez": mg["bez"], "jobs": jobs}

    cursor.close()
    conn.close()

    # Auftrag Info laden
    auftrag_info = AuftragInfo.query.all()

    return render_template(
        "vorrat.html",
        gruppen_jobs=gruppen_jobs,
        auftrag_info=auftrag_info
    )



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
