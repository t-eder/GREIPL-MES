import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, flash, url_for
import datetime as dt
from datetime import datetime
from config import connectionString

def get_lieferungen(Gruppe, DateMax, DateMin, ZustandMax, ZustandMin):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
            SELECT 
                DISPBEW.Auftrag,
                DISPBEW.BstArt,
                DISPBEW.EndTerm,
                DISPBEW.Teil,
                TEILE.Bez,
                TEILE.Gruppe,
                DISPBEW.MngAuftr,
                DISPBEW.MngBeweg,
                COALESCE(SUM(CASE WHEN LAGPLBST.Lag != 'N' THEN LAGPLBST.Mng ELSE 0 END), 0) AS BestandSumme
            FROM 
                INFRADB.dbo.DISPBEW DISPBEW
            JOIN 
                INFRADB.dbo.TEILE TEILE
                ON TEILE.Teil = DISPBEW.Teil
            LEFT JOIN 
                INFRADB.dbo.LAGPLBST LAGPLBST
                ON LAGPLBST.Teil = DISPBEW.Teil
            WHERE
                TEILE.Gruppe = '{Gruppe}'
                AND DISPBEW.EndTerm < '{DateMax}'
                AND DISPBEW.EndTerm > '{DateMin}'
                AND DISPBEW.Zustand >= '{ZustandMin}'
                AND DISPBEW.Zustand <= '{ZustandMax}'
                AND DISPBEW.Stat != 'E'
                AND DISPBEW.BstArt != 'F'
            GROUP BY
                DISPBEW.Auftrag,
                DISPBEW.BstArt,
                DISPBEW.EndTerm,
                DISPBEW.Teil,
                TEILE.Bez,
                TEILE.Gruppe,
                DISPBEW.MngAuftr,
                DISPBEW.MngBeweg
            ORDER BY
                DISPBEW.EndTerm;
        """
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()
        return records


@app.route('/lieferliste')
def lieferliste():
    gruppe = "E1"
    date_max = "2099-01-01 00:00:00"
    date_min = "2000-01-01 00:00:00"
    ZustandMin = 20
    ZustandMax = 50
    lieferungen = get_lieferungen(gruppe, date_max, date_min, ZustandMax, ZustandMin)
    heute = datetime.today()
    print(lieferungen)

    return render_template('lieferliste.html', lieferungen=lieferungen, heute=heute)


