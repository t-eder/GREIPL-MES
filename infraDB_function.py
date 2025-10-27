import pyodbc

from config import connectionString
from model import app, AuftragInfo, db


def CheckFAMat(FANR_list, ZustandMin=0, ZustandMax=59):
    with app.app_context():
        conn = pyodbc.connect(connectionString)
        cursor = conn.cursor()

        for FANR in FANR_list:
            SQL_QUERY = f"""
                SELECT 
                    FAPOS.Auftrag,
                    FAPOS.Zustand,              
                    FAPOS.Teil,                 
                    TEILE.Bez,                  
                    FAPOS.MngRest,
                    COALESCE(LAGPLBST_SUM.BestandSumme, 0) AS BestandSumme
                FROM INFRADB.dbo.FAPOS FAPOS
                JOIN INFRADB.dbo.TEILE TEILE ON FAPOS.Teil = TEILE.Teil
                LEFT JOIN (
                    SELECT 
                        Teil, 
                        COALESCE(SUM(CASE WHEN Lag != 'N' THEN Mng ELSE 0 END), 0) AS BestandSumme
                    FROM INFRADB.dbo.LAGPLBST
                    GROUP BY Teil
                ) LAGPLBST_SUM ON FAPOS.Teil = LAGPLBST_SUM.Teil
                WHERE
                    FAPOS.Auftrag = '{FANR}'
                    AND FAPOS.Zustand BETWEEN {ZustandMin} AND {ZustandMax}
                    AND FAPOS.Typ = 'M'
                    AND FAPOS.Stat != 'E'
            """
            cursor.execute(SQL_QUERY)
            records = cursor.fetchall()

            fehlteil = any(fa.MngRest is None or fa.MngRest > fa.BestandSumme for fa in records)

            auftrag_entry = AuftragInfo.query.filter_by(fa_nr=FANR).first()
            if auftrag_entry:
                auftrag_entry.fa_mat = fehlteil
            else:
                auftrag_entry = AuftragInfo(fa_nr=FANR, fa_mat=fehlteil)
                db.session.add(auftrag_entry)

        db.session.commit()
        print("Fehlteile für alle Aufträge geprüft!")

