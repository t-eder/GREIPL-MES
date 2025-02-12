import sqlite3

# Variablen am Anfang des Skripts definieren
db_path = "../instance/Databank.db"   # Pfad zur Datenbank
table_name = "task"                # Tabellenname
old_column_name = "Remain_quantity_order"    # Name der vorhandenen Spalte
new_column_name = "remain_quantity_order"    # Neuer Name der Spalte

# Verbindung zur Datenbank herstellen
connection = sqlite3.connect(db_path)
cursor = connection.cursor()

# 1. Überprüfen, ob die Tabelle existiert
try:
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
except sqlite3.OperationalError:
    print(f"Die Tabelle '{table_name}' existiert nicht.")
    connection.close()
    exit()

# 2. Überprüfen, ob die alte Spalte existiert
column_names = [col[1] for col in columns]
if old_column_name not in column_names:
    print(f"Die Spalte '{old_column_name}' existiert nicht in der Tabelle '{table_name}'.")
    connection.close()
    exit()

# 3. Überprüfen, ob die neue Spalte bereits existiert
if new_column_name in column_names:
    print(f"Eine Spalte mit dem Namen '{new_column_name}' existiert bereits.")
    connection.close()
    exit()

# 4. Spalte umbenennen
try:
    cursor.execute(f"ALTER TABLE {table_name} RENAME COLUMN {old_column_name} TO {new_column_name}")
    print(f"Die Spalte '{old_column_name}' wurde erfolgreich in '{new_column_name}' umbenannt.")
except sqlite3.OperationalError as e:
    print(f"Fehler beim Umbenennen der Spalte: {e}")

# Verbindung schließen
connection.commit()
connection.close()
