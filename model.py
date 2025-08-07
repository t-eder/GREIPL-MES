from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///Databank.db'
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Set up the upload folder here
app.config['UPLOAD_FOLDER'] = 'uploads'  # Make sure this is defined before using it

# 📌 Feste Pfade für Min- und Max-Kurven
MIN_TEMP_FILE = r"uploads/JEDEC_temp_max.csv"
MAX_TEMP_FILE = r"uploads/JEDEC_temp_min.csv"

# Verzeichnis für die hochgeladenen Dateien
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
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


class ProgrammierListe(db.Model):
    __tablename__ = 'ProgrammierListe'
    id = db.Column(db.Integer, primary_key=True)
    TYP = db.Column(db.String(10), nullable=True)
    GNR = db.Column(db.String(10), nullable=True)
    BEZ = db.Column(db.String(50), nullable=True)
    REV = db.Column(db.String(10), nullable=True)
    KND = db.Column(db.String(25), nullable=True, default="Kein FA")
    DAT = db.Column(db.String(10), nullable=True, default="Offen")
    SMT = db.Column(db.String(10), nullable=True, default="Offen")
    STC = db.Column(db.String(10), nullable=True, default="Offen")
    AOI = db.Column(db.String(10), nullable=True, default="Offen")
    THT = db.Column(db.String(10), nullable=True, default="Offen")
    AA = db.Column(db.String(10), nullable=True, default="Offen")
    COM = db.Column(db.String(250), nullable=True, default="")
    Done = db.Column(db.Boolean, default=False)
    Done_date = db.Column(db.String(10), nullable=True, default="Offen")
    FA_start = db.Column(db.String(15), nullable=True, default="Kein FA")
    PFAD = db.Column(db.String(256), nullable=True, default="")
