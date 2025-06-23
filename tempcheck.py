import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, send_file
from io import BytesIO
import threading

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


