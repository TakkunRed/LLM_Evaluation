import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "results.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                run_name TEXT,
                created_at TEXT NOT NULL,
                config TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                test_id TEXT NOT NULL,
                category TEXT NOT NULL,
                metric TEXT NOT NULL,
                prompt TEXT,
                response TEXT,
                score REAL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
        """)


def save_run(model_name: str, run_name: str, config: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO runs (model_name, run_name, created_at, config) VALUES (?, ?, ?, ?)",
            (model_name, run_name, datetime.now().isoformat(), json.dumps(config)),
        )
        return cur.lastrowid


def save_result(run_id: int, test_id: str, category: str, metric: str,
                prompt: str, response: str, score: float, details: dict):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO results
               (run_id, test_id, category, metric, prompt, response, score, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, test_id, category, metric, prompt, response, score,
             json.dumps(details, ensure_ascii=False), datetime.now().isoformat()),
        )


def get_runs():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC"
        ).fetchall()


def get_results_by_run(run_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM results WHERE run_id = ? ORDER BY category, metric",
            (run_id,),
        ).fetchall()


def get_summary_by_run(run_id: int):
    with get_connection() as conn:
        return conn.execute(
            """SELECT category, metric, AVG(score) as avg_score, COUNT(*) as count
               FROM results WHERE run_id = ?
               GROUP BY category, metric""",
            (run_id,),
        ).fetchall()
