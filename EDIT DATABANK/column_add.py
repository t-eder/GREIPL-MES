import sqlite3

# Variablen am Anfang des Skripts definieren
db_path = "../instance/Databank.db"  # Pfad zur Datenbank
table_name = "auftrag_info"                # Tabellenname
new_column_name = "Rahmen"    # Name der neuen Spalte
new_column_type = "Boolean"           # Datentyp der neuen Spalte

# Verbindung zur Datenbank herstellen
connection = sqlite3.connect(db_path)
cursor = connection.cursor()

# 1. Überprüfen, ob die Tabelle existiert
try:
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
except sqlite3.OperationalError:
    print(f"Die Tabelle '{table_name}' existiert nicht. Bitte stelle sicher, dass die Tabelle vorhanden ist.")
    connection.close()
    exit()

# 2. Neue Spalte hinzufügen (wenn sie nicht existiert)
try:
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {new_column_name} {new_column_type}")
    print(f"Spalte '{new_column_name}' mit Datentyp '{new_column_type}' wurde hinzugefügt.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print(f"Die Spalte '{new_column_name}' existiert bereits.")
    else:
        print(f"Ein Fehler ist aufgetreten: {e}")

# 3. Optional: Daten in der Tabelle anzeigen
cursor.execute(f"SELECT * FROM {table_name}")
inhalt = cursor.fetchall()
print(f"Inhalt der Tabelle '{table_name}':", inhalt)

# Verbindung schließen
connection.commit()
connection.close()
