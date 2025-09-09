import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, flash, url_for
import datetime as dt
from config import connectionString


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


def get_mat_buchungen(Buchungsdatum_min, Buchungsdatum_max, Erfassende, Teilegruppe, Buchungsart):
    with app.app_context():
        conn = pyodbc.connect(connectionString)

        # Basis-SQL-Abfrage ohne Erfassende- und Teilegruppen-Filter
        SQL_QUERY = f"""
            SELECT 
                DATEPART(MONTH, BEWEGUNG.AendDat) AS Kalenderwoche,
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
                DATEPART(MONTH, BEWEGUNG.AendDat), BEWEGUNG.Lag, TEILE.Gruppe
            ORDER BY 
                Kalenderwoche, BEWEGUNG.Lag
        """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        mat_buchungen = cursor.fetchall()
        return mat_buchungen


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
#  Meterialmengen nach Woche
    mat_buchungen = get_mat_buchungen("2020-01-10 00:00:00", "2100-01-01 00:00:00", ["mranz", "teder", "jbusc", "julli", "tfbg"], "", "AR")  # AR = Metrialentnahme
    buchungen_wochenweise = {}
    for row in mat_buchungen:
        kalenderwoche = row[0]
        lager = row[1]
        menge = float(row[2])  # ← Hier konvertieren wir Decimal zu float

        if kalenderwoche not in buchungen_wochenweise:
            buchungen_wochenweise[kalenderwoche] = {"A": 0, "E": 0}

        buchungen_wochenweise[kalenderwoche][lager] += menge

    return render_template('kpi.html', buchungen_wochenweise=buchungen_wochenweise, fa_wochenweise=fa_wochenweise, fa_fertig_wochenweise=fa_fertig_wochenweise, fa_fertig_jahr=fa_fertig_jahr)

