from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///Databank.db'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SECRET_KEY'] = 'SECRETKEY_GREIPL'
db = SQLAlchemy(app)


class Orders(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fanr = db.Column(db.String(12), nullable=False)
    ggnr = db.Column(db.String(12), nullable=False)
    bez = db.Column(db.String(50), nullable=False)
    gruppe =db.Column(db.String(20), nullable=True)
    rev = db.Column(db.String(10), nullable=True)
    art = db.Column(db.String(5), nullable=True)
    start = db.Column(db.String(15), nullable=True)
    end = db.Column(db.String(15), nullable=True)


class Personal(db.Model):
    pers_nr = db.Column(db.Integer, primary_key=True)
    gruppe = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(12), nullable=False)
    vorname = db.Column(db.String(12), nullable=False)
    stunden_tag = db.Column(db.Integer, nullable=False)
    tage_woche = db.Column(db.Integer, nullable=False)


class StundenKW(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pers_nr = db.Column(db.Integer, nullable=False)
    jahr = db.Column(db.Integer, nullable=False)
    kw = db.Column(db.Integer, nullable=False)
    stunden_kw = db.Column(db.Integer, nullable=False)
    stunden_korr = db.Column(db.Integer, nullable=True)
    korr_bemerk = db.Column(db.String(50), default="", nullable=True)


class WorkLoad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    kw = db.Column(db.Integer, nullable=False)
    gruppe = db.Column(db.Integer, nullable=False)
    h_ist = db.Column(db.Integer, nullable=True)
    h_plan = db.Column(db.Integer, nullable=True)


class AuftragInfo(db.Model):
    fa_nr = db.Column(db.Integer, primary_key=True)
    fa_mat = db.Column(db.Boolean, default=False)
    fa_bemerk = db.Column(db.String(200), default="")