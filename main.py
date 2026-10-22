import importlib.util
import sys
from pathlib import Path

import auftragsliste, arbeitvorrat, lieferliste, programmierliste, tempcheck, kpi, fehlteilliste, auslastung, linie, kapaplanung
from model import app, db, Personal
from flask import render_template, session, redirect, request, jsonify


# Der Bindestrich im Dateinamen verhindert einen normalen Python-Import.
# Das E-Mob-Modul registriert seine Routen direkt mit @app.route.
# Keine Blueprint-Registrierung erforderlich.
emob_module_path = Path(__file__).resolve().parent / 'kapaplanung-emob.py'
if not emob_module_path.is_file():
    raise FileNotFoundError(f'E-Mob-Modul nicht gefunden: {emob_module_path}')

emob_spec = importlib.util.spec_from_file_location('kapaplanung_emob', emob_module_path)
if emob_spec is None or emob_spec.loader is None:
    raise ImportError(f'E-Mob-Modul konnte nicht geladen werden: {emob_module_path}')

emob_module = importlib.util.module_from_spec(emob_spec)
sys.modules[emob_spec.name] = emob_module
try:
    emob_spec.loader.exec_module(emob_module)
except Exception:
    sys.modules.pop(emob_spec.name, None)
    raise


@app.route('/set_abteilung', methods=['POST'])
def set_abteilung():
    abteilung = request.form.get('abteilung')
    if abteilung:
        session['abteilung'] = abteilung
        return jsonify({'success': True, 'abteilung': abteilung})
    else:
        return jsonify({'success': False, 'message': 'Ungültige Abteilung'}), 400


@app.route('/personal/add', methods=['POST'])
def personal_add():
    pers_nr = request.form.get('pers_nr')
    gruppe = request.form.get('gruppe')
    name = request.form.get('name')
    vorname = request.form.get('vorname')
    stunden_tag = request.form.get('stunden_tag')
    tage_woche = request.form.get('tage_woche')

    new_personal = Personal(
        pers_nr=pers_nr,
        gruppe=gruppe,
        name=name,
        vorname=vorname,
        stunden_tag=stunden_tag,
        tage_woche=tage_woche
    )

    db.session.add(new_personal)
    db.session.commit()
    return redirect('/personal')


@app.route('/settings')
def settings():
    return render_template('settings.html')


@app.route('/tools')
def tools():
    return render_template('tools.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
