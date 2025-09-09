import pyodbc
from model import app, db, Personal, StundenKW, WorkLoad, AuftragInfo, MIN_TEMP_FILE, MAX_TEMP_FILE, ProgrammierListe
from flask import render_template, redirect, request, Flask, render_template, jsonify, flash, url_for
from config import connectionString



@app.route('/programmierliste', methods=['GET', 'POST'])
def programmierliste():
    if request.method == 'POST':

        #Bezeichnung, Index und KND aus Infra
        GreiplNr = request.form['GNR']
        conn = pyodbc.connect(connectionString)
        SQL_QUERY = f"""
                                           SELECT 
                                           TEILE.Bez, TEILE.AendIxSL
                                           FROM 
                                           INFRADB.dbo.TEILE TEILE
                                           WHERE
                                           TEILE.Teil = '{GreiplNr}'
                                           """

        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        record = cursor.fetchone()
        if record and len(record):
            InfraBez = record[0]
            InfraRev = record[1]
        else:
            # print("Keine gültigen Daten aus der Datenbank.")
            return "Keine gültigen Daten aus der Datenbank.", 404

        if request.form.getlist('SMD'):
            SMT = "Offen"
            STC = "Offen"
            AOI = "Offen"
        else:
            SMT = "nb"
            STC = "nb"
            AOI = "nb"

        if request.form.getlist('THT'):
            THT = "Offen"
        else:
            THT = "nb"

        new_task = ProgrammierListe(
            TYP=request.form['TYP'],
            GNR=request.form['GNR'],
            BEZ=InfraBez,
            REV=InfraRev,
            SMT=SMT,
            STC=STC,
            AOI=AOI,
            THT=THT,
            COM=request.form['COM'],
            PFAD=request.form['PFAD'],
        )
        db.session.add(new_task)
        db.session.commit()
        return redirect(url_for('programmierliste'))
    else:
        tasks = ProgrammierListe.query.all()
        update_fa_start_from_infra()
        return render_template('programmierliste.html', tasks=tasks)

def update_fa_start_from_infra():
    #  Programmierliste FA-Start aktualisieren
    open_tasks = ProgrammierListe.query.filter_by(Done=False).all()
    updated_count = 0

    with pyodbc.connect(connectionString) as conn:
        cursor = conn.cursor()

        for task in open_tasks:
            greipl_nr = task.GNR

            cursor.execute("""
                SELECT TOP 1 StartTerm, Knd
                FROM INFRADB.dbo.FKOPF
                WHERE Teil = ?
                  AND StartTerm >= GETDATE()
                  AND Zustand < 40
                ORDER BY StartTerm ASC
            """, (greipl_nr,))

            record = cursor.fetchone()
            if record and record[0]:
                try:
                    start_term = record[0].strftime('%d.%m.%y')
                except AttributeError:
                    start_term = str(record[0])

                # FKOPF.Knd aus dem record
                knd = record[1]

                # FA_start aktualisieren
                task.FA_start = start_term

                # Jetzt den Kunden-Bez (Name) holen
                cursor.execute("""
                    SELECT TOP 1 Bez
                    FROM INFRADB.dbo.KUNDE
                    WHERE Knd = ?
                """, (knd,))
                kunde_record = cursor.fetchone()
                if kunde_record:
                    task.KND = kunde_record[0]  # Feld in ProgrammierListe für Kundenbezeichnung

                updated_count += 1

        db.session.commit()

    return f"{updated_count} Einträge wurden aktualisiert."

@app.route('/update_comment_prog/<int:task_id>', methods=['POST'])
def update_comment_prog(task_id):
    #  Programmierliste Kommentar aktualisieren
    data = request.get_json()
    comment = data.get('comment', '')
    task = ProgrammierListe.query.get(task_id)
    if task:
        task.COM = comment
        db.session.commit()
        return jsonify({'success': True}), 200
    return jsonify({'error': 'Task not found'}), 404


@app.route('/delete_task/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    #  Programmierliste löschen eines Eintrags
    task = ProgrammierListe.query.get(task_id)
    if not task:
        return jsonify({'error': 'Nicht gefunden'}), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify({'success': True})

