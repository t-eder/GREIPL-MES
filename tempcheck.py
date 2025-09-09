import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, send_file
from io import BytesIO

app = Flask(__name__)

def load_csv_file(file_path):
    """ Lädt eine CSV-Datei mit Semikolon als Trennzeichen ein. """
    try:
        data = pd.read_csv(file_path, sep=";", decimal=",")
        data.iloc[:, 0] = pd.to_numeric(data.iloc[:, 0], errors="coerce")  # Zeit
        data.iloc[:, 1] = pd.to_numeric(data.iloc[:, 1], errors="coerce")  # Temperatur
        return data.dropna()  # Entferne Zeilen mit NaN-Werten
    except Exception as e:
        print(f"Fehler beim Laden der Datei {file_path}: {e}")
        return None


def adjust_time_to_50C(data):
    """ Setzt die Zeitachse auf 0 beim ersten Erreichen von 50°C. """
    mask = data.iloc[:, 1] >= 50  # Finde erste Stelle mit ≥ 50°C
    if mask.any():
        t_start = data.loc[mask.idxmax(), data.columns[0]]  # Erste Zeit bei 50°C
        data.iloc[:, 0] -= t_start  # Neue Zeitberechnung
        data = data[data.iloc[:, 0] >= 0]  # Entferne negative Zeiten
    return data


def plot_temperature_curve(measured_data, min_data, max_data):
    """ Erstellt eine Temperaturkurve mit Min-/Max-Grenzwerten und gibt das Plot als Bild zurück. """
    time_measured = measured_data.iloc[:, 0]
    temp_measured = measured_data.iloc[:, 1]

    time_min = min_data.iloc[:, 0]
    temp_min = min_data.iloc[:, 1]

    time_max = max_data.iloc[:, 0]
    temp_max = max_data.iloc[:, 1]

    # Interpolation der Min- und Max-Kurven auf die Messwerte-Zeitpunkte
    min_interp = np.interp(time_measured, time_min, temp_min)
    max_interp = np.interp(time_measured, time_max, temp_max)

    # Überprüfung auf Grenzverletzungen
    out_of_bounds = (temp_measured < min_interp) | (temp_measured > max_interp)

    # Diagramm erstellen
    plt.figure(figsize=(10, 5))
    plt.plot(time_measured, temp_measured, label="Messkurve", color="blue")
    plt.plot(time_measured, min_interp, label="Min-Kurve (JEDEC)", linestyle="dashed", color="green")
    plt.plot(time_measured, max_interp, label="Max-Kurve (JEDEC)", linestyle="dashed", color="red")

    # Markiere die Punkte außerhalb der Grenzen
    plt.scatter(time_measured[out_of_bounds], temp_measured[out_of_bounds], color='red',
                label='Grenzwert überschritten')

    plt.xlabel("Zeit (s)")
    plt.ylabel("Temperatur (°C)")
    plt.title("Reflow Temperaturprofil Analyse")
    plt.legend()
    plt.grid()

    # Bild im Speicher speichern und zurückgeben
    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plt.close()
    return img

def process_and_plot(measured_file_path, min_file, max_file, callback):
    """ Function to handle long-running file processing in a separate thread """
    try:
        measured_data = load_csv_file(measured_file_path)
        min_data = load_csv_file(min_file)
        max_data = load_csv_file(max_file)

        if measured_data is None or min_data is None or max_data is None:
            callback("Fehler beim Laden einer der Dateien.")
            return

        # Zeit auf 50°C-Startpunkt anpassen
        measured_data = adjust_time_to_50C(measured_data)

        # Temperaturkurve plotten und als Bild zurückgeben
        img = plot_temperature_curve(measured_data, min_data, max_data)
        callback(img)  # Callback with the image
    except Exception as e:
        callback(f"Fehler bei der Verarbeitung: {e}")


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
