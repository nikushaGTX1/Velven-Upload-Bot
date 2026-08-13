import sqlite3

from config import DB_PATH
from crypto_utils import encrypt_session


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            bot_user_id INTEGER PRIMARY KEY,
            telegram_account_id INTEGER NOT NULL,
            telegram_username TEXT,
            telegram_name TEXT NOT NULL,
            encrypted_session TEXT NOT NULL
        )""")


def save_user(bot_user_id, telegram_account_id, username, name, session):
    with connect() as db:
        db.execute("""INSERT INTO users VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bot_user_id) DO UPDATE SET
            telegram_account_id=excluded.telegram_account_id,
            telegram_username=excluded.telegram_username,
            telegram_name=excluded.telegram_name,
            encrypted_session=excluded.encrypted_session""",
            (bot_user_id, telegram_account_id, username, name, encrypt_session(session)))


def get_user(bot_user_id):
    with connect() as db:
        return db.execute("SELECT * FROM users WHERE bot_user_id = ?", (bot_user_id,)).fetchone()


def delete_user(bot_user_id):
    with connect() as db:
        db.execute("DELETE FROM users WHERE bot_user_id = ?", (bot_user_id,))
