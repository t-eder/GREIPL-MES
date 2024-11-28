import pyodbc
from model import app, db
from flask import render_template
import datetime as dt
from collections import defaultdict
from config import connectionString
def data_FA():
    with app.app_context():
        conn = pyodbc.connect(connectionString)

        Gruppe = "E1"
        ZustandMin = "10"
        ZustandMax = "50"
        DateMin = "2024-01-01 00:00:00"
        DateMax = "2025-30-01 00:00:00"
        Typ = "E"  # Auftrag = E; Arbeitsgang = A; Material = M;
        SQL_QUERY = f"""
                        SELECT 
                        FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez, FAPOS.Mng, FAPOS.StartTermPlan, FAPOS.EndTermPlan, FAPOS.PmNr, ARBPLATZ.Bez, FAPOS.Mng, FAPOS.MngGutIst
                        FROM 
                        INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                        WHERE
                        FAPOS.Teil = TEILE.Teil AND TEILE.Gruppe = '{Gruppe}' AND FAPOS.Zustand <= '{ZustandMax}' AND FAPOS.Zustand >= '{ZustandMin}' AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{Typ}'
                        AND FAPOS.StartTermPlan > '{DateMin}' AND FAPOS.StartTermPlan < '{DateMax}'
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
                                ORDER BY
                                FAPOS.StartTermPlan, FAPOS.EndTermPlan, FAPOS.Pos
                                """
    cursor = conn.cursor()
    cursor.execute(SQL_QUERY)
    records = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    jobs = [dict(zip(columns, row)) for row in records]
    return jobs

def get_job_ahead(jobs):
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;

    for job in jobs:
        auftrag = job['Auftrag']
        pos = job['Pos']
        # print(auftrag, pos)
        SQL_QUERY = f"""
                                    SELECT 
                                    FAPOS.Zustand, FAPOS.Auftrag, ARBPLATZ.Bez, FAPOS.Pos
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
            if r[3] < pos:
                job['job_ahead'] = r[2][:3]
                job['job_ahead_zustand']= r[0]
                # print(job)
                break
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
    kw_workload = defaultdict(list)
    l = ['2410-01', '2410-50', '2410-03', '2410-04', '2450-01']
    for AG in l:
        for (year, week), jobs in grouped_jobs.items():
            t = 0
            for job in jobs:
                if job['PmNr'] == AG:
                    t += job['Zeit']
            kw_workload[(year, week, AG)].append(int(t))
            # print("Zeit für 2410-01 in " + str(year) + "-" + str(week) + ": " + str(t))

    return(kw_workload)

@app.route('/')
def index():
    gruppe = "E1"
    zustand_min = "20"
    zustand_max = "50"
    date_min = "2024-01-01 00:00:00"
    date_max = "2025-30-12 00:00:00"
    masch_gruppe = 0

    jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    grouped_jobs = group_by_calendar_week(jobs)
    kw_workload = get_kw_workload(grouped_jobs)

    return render_template('index.html', jobs=jobs, grouped_jobs=grouped_jobs, kw_workload=kw_workload)

@app.route('/vorrat')
def vorrat():
    gruppe = "E1"
    zustand_min = "30"
    zustand_max = "50"
    date_min = "2010-01-01 00:00:00"
    date_max = "2024-31-12 00:00:00"


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

    masch_gruppe = "2450-01"  # Manuelle Handarbeit
    pruef_jobs = get_jobs(gruppe, masch_gruppe, zustand_min, zustand_max, date_min, date_max)
    get_job_ahead(pruef_jobs)
    get_delay(pruef_jobs)

    return render_template('vorrat.html', smd_jobs=smd_jobs, tht_jobs=tht_jobs, man_jobs=man_jobs, pruef_jobs=pruef_jobs)

@app.route('/settings')
def settings():

    return render_template('settings.html')

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    with app.app_context():  # Erstellt einen Anwendungscontext
        db.create_all()  # Erstellt die Datenbanktabellen
    app.run(host="0.0.0.0", port=8000, debug=True)



