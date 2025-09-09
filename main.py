import auftragsliste, arbeitvorrat, lieferliste, programmierliste, tempcheck, kpi
from model import app, db, Personal
from flask import  redirect, request, render_template

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


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    with app.app_context():  # Erstellt einen Anwendungscontext
        db.create_all()  # Erstellt die Datenbanktabellen
    app.run(host="0.0.0.0", port=5000, debug=True)
