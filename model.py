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
