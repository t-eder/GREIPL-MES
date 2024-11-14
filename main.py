import pyodbc
from model import app, db
from flask import render_template
import datetime as dt

def data_FA():
    with app.app_context():
        connectionString = "DSN=INFRADB;UID=infra;Trusted_Connection=Yes;APP=Microsoft Office;WSID=DUG-BLASCHKOB;DATABASE=INFRADB"
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
        connectionString = "DSN=INFRADB;UID=infra;Trusted_Connection=Yes;APP=Microsoft Office;WSID=DUG-BLASCHKOB;DATABASE=INFRADB"
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

def get_calendar_week_and_year(date):
    # Assuming date is already a datetime object
    calendar_week = date.isocalendar()[1]
    year = date.year
    return calendar_week, year
@app.route('/')
def index():
    orders = data_FA()

    orders.sort(key=lambda x: x[5])

    orders_by_week_and_year = {}
    for order in orders:
        week, year = get_calendar_week_and_year(order[5])  # Using the start date to determine the calendar week and year
        key = f"Week {week}, {year}"
        if key not in orders_by_week_and_year:
            orders_by_week_and_year[key] = []
        orders_by_week_and_year[key].append(order)

    return render_template('index.html', orders=orders, orders_by_week_and_year=orders_by_week_and_year)

def get_jobs(gruppe, masch_gruppe ,zustand_min, zustand_max, date_min, date_max):
    connectionString = "DSN=INFRADB;UID=infra;Trusted_Connection=Yes;APP=Microsoft Office;WSID=DUG-BLASCHKOB;DATABASE=INFRADB"
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;
    SQL_QUERY = f"""
                            SELECT 
                            FAPOS.Zustand, FAPOS.Auftrag, TEILE.Teil, TEILE.Bez, FAPOS.Mng, FAPOS.StartTermPlan,
                            FAPOS.EndTermPlan, FAPOS.PmNr, FAPOS.Mng, FAPOS.MngRest, FAPOS.Zeit, FAPOS.Pos,
                            FAPOS.ZeitIst, FAPOS.Bez AS posbez
                            FROM 
                            INFRADB.dbo.FAPOS FAPOS, INFRADB.dbo.TEILE TEILE, INFRADB.dbo.ARBPLATZ ARBPLATZ
                            WHERE
                            FAPOS.Teil = TEILE.Teil AND TEILE.Gruppe = '{gruppe}' AND FAPOS.Zustand <= '{zustand_max}' AND FAPOS.Zustand >= '{zustand_min}' AND FAPOS.PmNr = ARBPLATZ.PmNr AND FAPOS.Typ = '{typ}'
                            AND FAPOS.StartTermPlan > '{date_min}' AND FAPOS.StartTermPlan < '{date_max}' AND FAPOS.PmNr = '{masch_gruppe}'
                            ORDER BY
                            FAPOS.StartTermPlan, FAPOS.EndTermPlan
                            """

    cursor = conn.cursor()
    cursor.execute(SQL_QUERY)
    records = cursor.fetchall()
    columns = [column[0] for column in cursor.description]
    jobs = [dict(zip(columns, row)) for row in records]
    return jobs


def get_job_ahead(jobs):
    connectionString = "DSN=INFRADB;UID=infra;Trusted_Connection=Yes;APP=Microsoft Office;WSID=DUG-BLASCHKOB;DATABASE=INFRADB"
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;

    for job in jobs:
        auftrag = job['Auftrag']
        pos = job['Pos']
        print(auftrag, pos)
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
        print(records)

        for r in records:
            if r[3] < pos:
                job['job_ahead'] = r[2][:3]
                job['job_ahead_zustand']= r[0]
                print(job)
                break
    return jobs

def get_delay(jobs):
    connectionString = "DSN=INFRADB;UID=infra;Trusted_Connection=Yes;APP=Microsoft Office;WSID=DUG-BLASCHKOB;DATABASE=INFRADB"
    conn = pyodbc.connect(connectionString)
    typ = "A"  # Auftrag = E; Arbeitsgang = A; Material = M;

    for job in jobs:
        auftrag = job['Auftrag']
        pos = job['Pos']
        print(auftrag, pos)
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
        print(records)

        for r in records:
            delay = (r[1] - dt.datetime.today()).days
            print(delay)
            job['delay'] = delay
            print(job)
    return jobs



@app.route('/vorrat')
def vorrat():
    gruppe = "E1"
    zustand_min = "30"
    zustand_max = "50"
    date_min = "2010-01-01 00:00:00"
    date_max = "2024-1-12 00:00:00"


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

    return render_template('vorrat.html', smd_jobs=smd_jobs, tht_jobs=tht_jobs, man_jobs=man_jobs)

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    with app.app_context():  # Erstellt einen Anwendungscontext
        db.create_all()  # Erstellt die Datenbanktabellen
    app.run(host="0.0.0.0", port=8000, debug=True)



