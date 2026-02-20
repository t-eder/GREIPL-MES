import pandas as pd
import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, session
import datetime as dt
from datetime import datetime
from config import connectionString

def get_fehlteile(ZustandMin, ZustandMax):
    """
    Liefert alle Fehlteile (FAPOS), deren Auftrag zu einem Endprodukt der Gruppe 'M1' gehört
    und deren Auftrag-Zustand zwischen ZustandMin und ZustandMax liegt.
    H- und F-Teile werden ausgeschlossen.
    """
    with app.app_context():
        conn = pyodbc.connect(connectionString)

        SQL_QUERY = f"""
            SELECT 
                FKOPF.StartTerm,
                FAPOS.Auftrag,
                FKOPF.Teil AS Endprodukt,
                TEILE2.Bez AS Endprodukt_Bez,
                FKOPF.Zustand AS Auftrag_Zustand,
                FAPOS.Zustand,
                FAPOS.Teil,
                TEILE.Bez AS Bezeichnung,
                FAPOS.MngRest,
                COALESCE(SUM(CASE WHEN LAGPLBST.Lag != 'N' THEN LAGPLBST.Mng ELSE 0 END), 0) AS BestandSumme
            FROM 
                INFRADB.dbo.FAPOS AS FAPOS
            INNER JOIN INFRADB.dbo.FKOPF AS FKOPF 
                ON FAPOS.Auftrag = FKOPF.Auftrag
            INNER JOIN INFRADB.dbo.TEILE AS TEILE 
                ON FAPOS.Teil = TEILE.Teil
            INNER JOIN INFRADB.dbo.TEILE AS TEILE2 
                ON FKOPF.Teil = TEILE2.Teil
            LEFT JOIN INFRADB.dbo.LAGPLBST AS LAGPLBST
                ON LAGPLBST.Teil = FAPOS.Teil
            WHERE
                FAPOS.Stat != 'E'
                AND FAPOS.Typ = 'M'
                AND FKOPF.Zustand >= '{ZustandMin}'
                AND FKOPF.Zustand <= '{ZustandMax}'
                AND TEILE2.Gruppe = 'M1'
                AND FAPOS.SollAbbuch != '1'
                AND TEILE.Stat != 'P'
                AND TEILE.Gruppe != 'M1'
            GROUP BY
                FKOPF.StartTerm,
                FAPOS.Auftrag,
                FKOPF.Teil,
                TEILE2.Bez,
                FKOPF.Zustand,
                FAPOS.Zustand,
                FAPOS.Teil,
                TEILE.Bez,
                FAPOS.MngRest
            ORDER BY 
                FKOPF.StartTerm, FAPOS.Auftrag, BestandSumme, FAPOS.Zustand
        """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        records = cursor.fetchall()

        # Print-Ausgabe wie gewünscht
        for r in records:
            print(r[0], end="; ")
            print(r[1], end="; ")
            print(r[2], end="; ")
            print(r[3], end="; ")
            print(r[4], end="; ")
            print(r[5], end="; ")
            print(r[6], end="; ")
            print(r[7], end="; ")
            print(r[8], end="; ")
            print(r[9])

        conn.close()
        return records

@app.route('/fehlteilliste')
def fehlteilliste():
    ZustandMin = 50
    ZustandMax = 50
    fehlteile = get_fehlteile(ZustandMin, ZustandMax)
    heute = datetime.today()
    return render_template(
        "fehlteilliste.html",
        fehlteile=fehlteile,
        heute=heute
    )



