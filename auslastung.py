import pyodbc
from model import app
from flask import request, make_response
from config import connectionString
import pandas as pd
import plotly.express as px


def get_utilization_data(pmnr, datemin, datemax):
    """
    Führt die SQL-Abfrage aus und gibt die Ergebnisse als DataFrame zurück.
    """
    try:
        with app.app_context():
            conn = pyodbc.connect(connectionString)

            SQL_QUERY = """
                SELECT 
                    RUECK.Stat, RUECK.Person, RUECK.StartTerm, RUECK.EndTerm
                FROM INFRADB.dbo.RUECK RUECK
                WHERE
                    RUECK.StartTerm >= ? AND RUECK.StartTerm <= ? AND RUECK.PmNr = ?
                ORDER BY RUECK.StartTerm ASC
            """

            df = pd.read_sql(SQL_QUERY, conn, params=[datemin, datemax, pmnr])
            conn.close()

            df['StartTerm'] = pd.to_datetime(df['StartTerm'])
            df['EndTerm'] = pd.to_datetime(df['EndTerm'])
            df = df.drop_duplicates()

            return df

    except Exception as e:
        print(f"Fehler beim Abrufen der Datenbankdaten: {e}")
        return pd.DataFrame(columns=['Stat', 'Person', 'StartTerm', 'EndTerm'])


@app.route('/auslastung', methods=['GET', 'POST'])
def auslastung():
    if request.method == 'POST':
        pmnr = request.form.get('pmnr', '').strip()
        jahr = request.form.get('jahr', '').strip()

        if not pmnr:
            return "Bitte geben Sie eine PmNr ein.", 400
        if not jahr or not jahr.isdigit():
            return "Bitte geben Sie ein gültiges Jahr ein (z. B. 2025).", 400

        # Zeitraum automatisch auf das gesamte Jahr setzen
        datemin = f"{jahr}-01-01 00:00:00"
        datemax = f"{jahr}-31-12 23:59:59"

        df = get_utilization_data(pmnr, datemin, datemax)

        if df.empty:
            return f"Keine Daten für PmNr {pmnr} im Jahr {jahr} gefunden.", 200

        # ➤ NEU: Dauer berechnen (in Stunden)
        df["Dauer_h"] = (df["EndTerm"] - df["StartTerm"]).dt.total_seconds() / 3600

        # ➤ NEU: Farbkennzeichnung je nach Dauer
        df["Farbe"] = df["Dauer_h"].apply(lambda h: "Über 10h" if h > 10 else "Unter 10h")

        # ➤ NEU: Farbschema definieren (rot für lange, blau für kurze)
        color_map = {
            "Über 10h": "red",
            "Unter 10h": "steelblue"
        }

        # Plotly Gantt-Diagramm erstellen
        fig = px.timeline(
            df,
            x_start="StartTerm",
            x_end="EndTerm",
            y="Person",
            color="Farbe",  # <-- jetzt nach Dauer gefärbt
            color_discrete_map=color_map,
            title=f"Maschinenbelegung PmNr {pmnr} im Jahr {jahr}",
            labels={
                "Person": "Bearbeiter",
                "StartTerm": "Startzeitpunkt",
                "EndTerm": "Endzeitpunkt",
                "Farbe": "Dauer",
            },
            height=600
        )

        fig.update_yaxes(categoryorder="trace")
        graph_html = fig.to_html(full_html=False)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Maschinenbelegung</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Arial', sans-serif; margin: 20px; }}
                h2 {{ color: #1E40AF; border-bottom: 2px solid #93C5FD; padding-bottom: 10px; }}
                form {{ margin-bottom: 20px; }}
                input, button {{ padding: 8px; font-size: 1em; margin-right: 8px; }}
            </style>
        </head>
        <body>
            <h2>Maschinenauslastung (Gantt-Diagramm)</h2>
            <form method="POST" action="/auslastung">
                <label for="pmnr">PmNr:</label>
                <input type="text" id="pmnr" name="pmnr" value="{pmnr}" required>
                <label for="jahr">Jahr:</label>
                <input type="number" id="jahr" name="jahr" value="{jahr}" min="2000" max="2100" required>
                <button type="submit">Anzeigen</button>
            </form>
            <p>Anzeige der Belegungszeiten der Maschine <b>{pmnr}</b> im Jahr <b>{jahr}</b>.<br>
            <span style='color:red;'>Rot = länger als 10 Stunden</span>, 
            <span style='color:steelblue;'>Blau = kürzer als 10 Stunden</span></p>
            <div id="plotly-chart" style="width: 100%; height: 90vh;">
                {graph_html}
            </div>
        </body>
        </html>
        """
        return make_response(html_content)

    # Wenn GET: Nur Eingabeformular anzeigen
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Maschinenauslastung</title>
        <meta charset="utf-8">
        <style>
            body { font-family: 'Arial', sans-serif; margin: 20px; }
            h2 { color: #1E40AF; border-bottom: 2px solid #93C5FD; padding-bottom: 10px; }
            form { margin-top: 20px; }
            input, button { padding: 8px; font-size: 1em; margin-right: 8px; }
        </style>
    </head>
    <body>
        <h2>Maschinenauslastung (Gantt-Diagramm)</h2>
        <form method="POST" action="/auslastung">
            <label for="pmnr">PmNr:</label>
            <input type="text" id="pmnr" name="pmnr" placeholder="z.B. 2410-03" required>
            <label for="jahr">Jahr:</label>
            <input type="number" id="jahr" name="jahr" placeholder="z.B. 2025" min="2000" max="2100" required>
            <button type="submit">Anzeigen</button>
        </form>
    </body>
    </html>
    """
