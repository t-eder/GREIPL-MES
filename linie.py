import os
import json
import pyodbc
from flask import render_template, request, jsonify
from model import app
from config import connectionString
from datetime import date, datetime, timedelta
import isoweek


# ------------------------------------------------------------
#   DB-Hilfsfunktionen
# ------------------------------------------------------------

def get_lieferungen(Gruppe, TerminMax, ZustandMax, ZustandMin):
    conn = pyodbc.connect(connectionString)
    cursor = conn.cursor()

    SQL = f"""
        SELECT 
            DISPBEW.LiefKnd,
            DISPBEW.Auftrag,
            DISPBEW.Stat,
            DISPBEW.Zustand,
            DISPBEW.BstArt,
            DISPBEW.EndTerm,
            DISPBEW.Teil,
            TEILE.Bez,
            TEILE.Gruppe,
            DISPBEW.MngAuftr,
            DISPBEW.MngBeweg,
            FKOPF.Auftrag AS FA,
            FKOPF.Zustand AS FAZustand,
            FKOPF.StartTerm AS FAStartTerm,
            FKOPF.Mng AS FAMenge
            
        FROM INFRADB.dbo.DISPBEW DISPBEW
        JOIN INFRADB.dbo.TEILE TEILE
            ON TEILE.Teil = DISPBEW.Teil
        JOIN INFRADB.dbo.FKOPF FKOPF
            ON FKOPF.Teil = DISPBEW.Teil
        WHERE
            TEILE.Gruppe = ?
            AND DISPBEW.LiefKnd IN ('11731','11743','11742')
            AND DISPBEW.EndTerm > ?
            AND DISPBEW.Stat != 'E'
            AND DISPBEW.Zustand BETWEEN ? AND ?
            AND DISPBEW.BstArt = 'K'
            AND ( 
                TEILE.Bez LIKE '%P40%' OR 
                TEILE.Bez LIKE '%P45%' OR 
                TEILE.Bez LIKE '%W40%'
            )
        ORDER BY 
            DISPBEW.EndTerm,
            DISPBEW.Auftrag
    """

    cursor.execute(SQL, (Gruppe, TerminMax, ZustandMin, ZustandMax))
    data = cursor.fetchall()
    conn.close()
    return data


def get_FA(Gruppe, ZustandMin, ZustandMax, DateMax, DateMin, Typ, filters):
    conn = pyodbc.connect(connectionString)
    cursor = conn.cursor()

    sql = """
        SELECT 
            FAPOS.Typ,
            FAPOS.Zustand, 
            FAPOS.Auftrag, 
            TEILE.Teil, 
            TEILE.Bez, 
            FAPOS.Mng, 
            FAPOS.StartTerm,
            FAPOS.EndTerm, 
            FAPOS.MngRest,
            FAPOS.Zeit
        FROM INFRADB.dbo.FAPOS FAPOS
        JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
        JOIN INFRADB.dbo.ARBPLATZ ARBPLATZ ON FAPOS.PmNr = ARBPLATZ.PmNr
        WHERE
            TEILE.Gruppe = ?
            AND FAPOS.Zustand >= ? AND FAPOS.Zustand <= ?
            AND FAPOS.Typ = ?
            AND FAPOS.StartTerm BETWEEN ? AND ?
            AND NOT (FAPOS.Stat = 'E' AND FAPOS.Zustand < 60)
    """

    params = [Gruppe, ZustandMin, ZustandMax, Typ, DateMin, DateMax]

    # LIKE-Filters dynamisch einbauen
    if filters:
        like_sql = " OR ".join(["TEILE.Bez LIKE ?"] * len(filters))
        sql += f" AND ({like_sql})"
        params.extend([f"%{f}%" for f in filters])

    sql += " ORDER BY FAPOS.StartTermPlan, FAPOS.EndTermPlan"

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------
#   Kapazitätsdatei
# ------------------------------------------------------------

KAPAZITAET_FILE = os.path.join(os.path.dirname(__file__), "static", "data", "kapazitaet.json")
KAPAZITAET_DEFAULT = 1  # Standard-Kapazität

def load_kapazitaet():
    folder = os.path.dirname(KAPAZITAET_FILE)
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists(KAPAZITAET_FILE):
        base = {"Endmontage": {}, "HAK": {}, "Anschlussmodule": {}}
        save_kapazitaet(base)
        return base

    with open(KAPAZITAET_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_kapazitaet(data):
    with open(KAPAZITAET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ------------------------------------------------------------
#   Wochenberechnung
# ------------------------------------------------------------

def compute_week_sums(records):
    """
    records: Liste FA-Objekte mit EndTermPlan + Zeit in MINUTEN
    Rückgabe: { "2025-KW46": 123.5 }
    """
    result = {}

    for FA in records:
        if not FA.StartTerm:
            continue

        iso = FA.StartTerm.isocalendar()
        key = f"{iso[0]}-KW{iso[1]:02d}"

        minuten = FA.Zeit or 0
        stunden = minuten / 60

        result[key] = result.get(key, 0) + stunden

    return result


from decimal import Decimal
from collections import defaultdict


def sum_weeks(weeks, kap):
    """
    weeks: dict der Form {Bereich: {KW: Stunden}}
    kap: dict der Form {Bereich: {KW: Kapazität}}

    Rückgabe: dict {KW: {"sum_val": Stunden, "sum_kap": Kapazität, "sum_percent": Prozent}}
    """
    alle_wochen = set()
    for week_data in weeks.values():
        alle_wochen.update(week_data.keys())
    alle_wochen = sorted(alle_wochen)

    gesamt = {}
    for week in alle_wochen:
        sum_val = sum(Decimal(week_data.get(week, 0)) for week_data in weeks.values())
        sum_kap = sum(kap.get(bereich, {}).get(week, 0) for bereich in weeks.keys())
        sum_percent = round((sum_val / sum_kap * 100), 1) if sum_kap > 0 else 0
        gesamt[week] = {
            "sum_val": sum_val,
            "sum_kap": sum_kap,
            "sum_percent": sum_percent
        }
    return gesamt

# ------------------------------------------------------------
#   Haupt-Route – Liniensicht
# ------------------------------------------------------------

@app.route('/linie', methods=['GET'])
def linie():

    heute = datetime.today()
    date_max = (heute + timedelta(weeks=8)).strftime("%Y-%d-%m 00:00:00")
    date_min = (heute - timedelta(weeks=2)).strftime("%Y-%d-%m 00:00:00")
    print(date_max, date_min)
    # --------------------------------------------------------
    # DB-Daten laden
    # --------------------------------------------------------
    Endmontage = get_FA("M1", 10, 60, date_max, date_min, "A", ("P40", "P45", "W40"))
    Zusatzgehaeuse = get_FA("M1", 10, 60, date_max, date_min, "A", ("Zusatzgehäuse",))
    Anschlussmodul = get_FA("M1", 10, 60, date_max, date_min, "A",
                            ("Anschlussmodul W40", "Anschlussmodul P45", "Anschlussmodul P40"))

    # --------------------------------------------------------
    # Wochen aufsummieren
    # --------------------------------------------------------
    weeks = {
        "Endmontage": compute_week_sums(Endmontage),
        "HAK": compute_week_sums(Zusatzgehaeuse),
        "Anschlussmodule": compute_week_sums(Anschlussmodul)
    }


    print(weeks)


    # Aktuelle Kalenderwoche berechnen
    current_week = f"{date.today().year}-KW{isoweek.Week.thisweek().week:02d}"

    kap = load_kapazitaet()
    gesamt = sum_weeks(weeks, kap)
    print(gesamt)

    ## Lieferungen
    date_min = (heute - timedelta(weeks=4)).strftime("%Y-%d-%m 00:00:00")
    Liefertermine = get_lieferungen('M1', date_min, 50, 10)
    print(Liefertermine)

    return render_template(
        "linie.html",
        Endmontage=Endmontage,
        Zusatzgehaeuse=Zusatzgehaeuse,
        Anschlussmodul=Anschlussmodul,
        weeks=weeks,
        gesamt=gesamt,
        current_week=current_week,
        kap=kap,
        kapazitaet_default=KAPAZITAET_DEFAULT,
        bereiche=["Endmontage", "HAK", "Anschlussmodule"],
        Liefertermine=Liefertermine,
        timedelta=timedelta
    )


# ------------------------------------------------------------
#   AJAX – Kapazität ändern
# ------------------------------------------------------------

@app.route('/update_kapazitaet', methods=['POST'])
def update_kapazitaet():
    data = request.get_json(force=True)

    bereich = data.get("bereich")
    kw = data.get("kw")
    stunden = data.get("stunden")

    if not bereich or not kw:
        return jsonify({"status": "error", "msg": "Fehlende Parameter"}), 400

    try:
        stunden = int(stunden)
    except:
        return jsonify({"status": "error", "msg": "Stunden muss Zahl sein"}), 400

    kap = load_kapazitaet()
    kap.setdefault(bereich, {})
    kap[bereich][kw] = stunden
    save_kapazitaet(kap)

    return jsonify({"status": "ok", "bereich": bereich, "kw": kw, "stunden": stunden})
