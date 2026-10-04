"""Transactional SQLite storage for calculation inputs, never projected results."""

import json
import sqlite3
from contextlib import contextmanager


class PlannerStore:
    """Store planner inputs and separate bank observations in one SQLite file."""
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            # user_version tracks the schema, not the application version.
            # Refuse newer schemas rather than accidentally modifying unknown data.
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise RuntimeError("This database was created by a newer planner version.")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS money_objects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
                    starting_cents INTEGER NOT NULL, monthly_income_cents INTEGER NOT NULL,
                    funding_type TEXT NOT NULL, external_source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS periodic_plans (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES money_objects(id),
                    destination_id TEXT NOT NULL REFERENCES money_objects(id),
                    amount_cents INTEGER NOT NULL, use_rest INTEGER NOT NULL,
                    priority INTEGER NOT NULL, start_month INTEGER NOT NULL,
                    end_month INTEGER NOT NULL, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS consumption_plans (
                    id TEXT PRIMARY KEY, payer_id TEXT NOT NULL REFERENCES money_objects(id),
                    title TEXT NOT NULL, amount_cents INTEGER NOT NULL, month INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bank_items (
                    id TEXT PRIMARY KEY, token BLOB NOT NULL, institution TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bank_accounts (
                    id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES bank_items(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, mask TEXT, currency TEXT, current_cents INTEGER,
                    available_cents INTEGER, fetched_at TEXT NOT NULL,
                    money_object_id TEXT REFERENCES money_objects(id) ON DELETE SET NULL);
                PRAGMA user_version = 2;
            """)

    @contextmanager
    def connect(self):
        """Commit on success, roll back on error, and always close the connection."""
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self):
        with self.connect() as db:
            return {
                "objects": [dict(row) for row in db.execute("SELECT * FROM money_objects ORDER BY rowid")],
                "transfers": [dict(row) for row in db.execute("SELECT * FROM periodic_plans ORDER BY rowid")],
                "consumption": [dict(row) for row in db.execute("SELECT * FROM consumption_plans ORDER BY rowid")],
                "settings": {row["key"]: json.loads(row["value"])
                             for row in db.execute("SELECT * FROM settings")},
            }

    def save(self, state):
        with self.connect() as db:
            # A failed write rolls the entire snapshot back to the previous state.
            db.execute("DELETE FROM consumption_plans")
            db.execute("DELETE FROM periodic_plans")
            # Replace plan rows to preserve their saved order (priority ties use it).
            # Update money objects in place: deleting them on every save would clear
            # bank-account mappings through ON DELETE SET NULL.
            for table, key in (("money_objects", "objects"),
                               ("periodic_plans", "transfers"),
                               ("consumption_plans", "consumption")):
                for row in state[key]:
                    columns = list(row)
                    updates = ', '.join(f'{column}=excluded.{column}' for column in columns if column != 'id')
                    db.execute(f'INSERT INTO {table} ({", ".join(columns)}) '
                               f'VALUES ({", ".join("?" for _ in columns)}) '
                               f'ON CONFLICT(id) DO UPDATE SET {updates}',
                               [row[column] for column in columns])
            wanted = {row['id'] for row in state['objects']}
            for row in db.execute('SELECT id FROM money_objects').fetchall():
                if row['id'] not in wanted:
                    db.execute('DELETE FROM money_objects WHERE id=?', (row['id'],))
            db.execute("DELETE FROM settings")
            db.executemany("INSERT INTO settings VALUES (?, ?)",
                           [(key, json.dumps(value)) for key, value in state["settings"].items()])
