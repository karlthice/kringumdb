"""
One-time migration script: SQL Server (iceland) -> SQLite (kringum.db)
Requires: pyodbc, SQL Server Express with iceland database restored
"""
import pyodbc
import sqlite3
import os
import sys

SQLSERVER_CONN = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=.\\SQLEXPRESS;"
    "Database=iceland;"
    "Trusted_Connection=yes;"
)

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kringum.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caption TEXT NOT NULL,
    caption_eng TEXT NOT NULL DEFAULT '',
    description TEXT,
    description_eng TEXT,
    media TEXT,
    visibility INTEGER NOT NULL DEFAULT 0,
    gps TEXT,
    radius INTEGER
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    gps TEXT,
    tag TEXT,
    story TEXT,
    ref TEXT,
    fromdate TEXT,
    todate TEXT,
    source TEXT,
    lastchanged TEXT,
    story_eng TEXT,
    name_eng TEXT,
    link TEXT,
    link_eng TEXT,
    visibility INTEGER DEFAULT 0
);
"""


def migrate():
    # Connect to SQL Server
    print("Connecting to SQL Server...")
    try:
        mssql = pyodbc.connect(SQLSERVER_CONN)
    except Exception as e:
        print(f"Error connecting to SQL Server: {e}")
        sys.exit(1)

    mssql_cursor = mssql.cursor()

    # Remove old SQLite file if it exists
    if os.path.exists(SQLITE_PATH):
        os.remove(SQLITE_PATH)
        print(f"Removed existing {SQLITE_PATH}")

    # Create SQLite database
    print(f"Creating SQLite database at {SQLITE_PATH}...")
    lite = sqlite3.connect(SQLITE_PATH)
    lite.executescript(SCHEMA)

    # Migrate areas
    print("Migrating areas...")
    mssql_cursor.execute("SELECT id, caption, caption_eng, description, description_eng, media, visibility, gps, radius FROM areas ORDER BY id")
    area_rows = mssql_cursor.fetchall()
    for row in area_rows:
        lite.execute(
            "INSERT INTO areas (id, caption, caption_eng, description, description_eng, media, visibility, gps, radius) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row.id, row.caption, row.caption_eng, row.description, row.description_eng, row.media, row.visibility, row.gps, row.radius)
        )
    print(f"  Migrated {len(area_rows)} areas")

    # Migrate items
    print("Migrating items...")
    mssql_cursor.execute("SELECT Id, name, gps, tag, story, ref, fromdate, todate, source, lastchanged, story_eng, name_eng, link, link_eng, visibility FROM items ORDER BY Id")
    item_rows = mssql_cursor.fetchall()
    for row in item_rows:
        lastchanged = row.lastchanged.isoformat() if row.lastchanged else None
        lite.execute(
            "INSERT INTO items (id, name, gps, tag, story, ref, fromdate, todate, source, lastchanged, story_eng, name_eng, link, link_eng, visibility) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row.Id, row.name, row.gps, row.tag, row.story, row.ref, row.fromdate, row.todate, row.source, lastchanged, row.story_eng, row.name_eng, row.link, row.link_eng, row.visibility)
        )
    print(f"  Migrated {len(item_rows)} items")

    lite.commit()
    lite.close()
    mssql.close()

    # Verify
    print("\nVerification:")
    lite = sqlite3.connect(SQLITE_PATH)
    area_count = lite.execute("SELECT COUNT(*) FROM areas").fetchone()[0]
    item_count = lite.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"  Areas: {area_count}")
    print(f"  Items: {item_count}")
    lite.close()
    print("\nMigration complete!")


if __name__ == '__main__':
    migrate()
