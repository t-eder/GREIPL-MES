import sqlite3

db_path = "../instance/Databank.db"
table_name = "task"
column_name = "deliver_stop"
new_value = "0"
row_id = 3

try:
    # Verbindung zur Datenbank herstellen
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    # Dynamisches SQL-Update-Statement
    sql = f"UPDATE {table_name} SET {column_name} = ? WHERE id = ?"
    cursor.execute(sql, (new_value, row_id))

    # Änderungen speichern
    connection.commit()

    # Prüfen, ob eine Zeile geändert wurde
    if cursor.rowcount == 0:
        print(f"Keine Zeile mit ID {row_id} in der Tabelle '{table_name}' gefunden.")
    else:
       print(f"Zeile mit ID {row_id} erfolgreich aktualisiert: {column_name} = {new_value}")

except sqlite3.OperationalError as e:
        print(f"Ein Fehler ist aufgetreten: {e}")

finally:
    # Verbindung schließen
    connection.close()
