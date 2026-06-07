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


def update_result_score(run_id: int, test_id: str, score: float, manual: bool = True):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT details FROM results WHERE run_id = ? AND test_id = ?",
            (run_id, test_id),
        ).fetchone()
        if row:
            details = json.loads(row["details"]) if row["details"] else {}
            details["manual_score"] = manual
            conn.execute(
                "UPDATE results SET score = ?, details = ? WHERE run_id = ? AND test_id = ?",
                (score, json.dumps(details, ensure_ascii=False), run_id, test_id),
            )


def merge_runs(
    run_ids_by_priority: list[int],
    merged_name: str,
    overrides: dict[str, int] | None = None,
) -> int:
    """複数runをマージして新しいrunを作成する。

    run_ids_by_priority: 優先度順のrun_idリスト（先頭が最優先）
    merged_name: 新しいrunの名前
    overrides: {test_id: run_id} テストケースごとの個別優先指定
    Returns: 新しいrun_id
    """
    overrides = overrides or {}

    # 各runの結果を収集 {run_id: {test_id: row_dict}}
    run_results: dict[int, dict[str, dict]] = {}
    run_model_names: list[str] = []
    with get_connection() as conn:
        for run_id in run_ids_by_priority:
            rows = conn.execute(
                "SELECT * FROM results WHERE run_id = ?", (run_id,)
            ).fetchall()
            run_results[run_id] = {row["test_id"]: dict(row) for row in rows}
            run_row = conn.execute(
                "SELECT model_name, run_name FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run_row:
                run_model_names.append(run_row["run_name"] or run_row["model_name"])

    all_test_ids: set[str] = set()
    for results in run_results.values():
        all_test_ids.update(results.keys())

    config = {
        "is_merged": True,
        "merged_from": run_ids_by_priority,
        "priority_order": run_ids_by_priority,
        "source_labels": run_model_names,
        "overrides": overrides,
    }
    model_label = "merged: " + " / ".join(run_model_names)
    new_run_id = save_run(model_label, merged_name, config)

    for test_id in sorted(all_test_ids):
        # overrideがあればそのrunを優先
        if test_id in overrides:
            source_id = overrides[test_id]
            row = run_results.get(source_id, {}).get(test_id)
            if row is None:
                # fallback to priority order
                for rid in run_ids_by_priority:
                    if test_id in run_results[rid]:
                        row = run_results[rid][test_id]
                        source_id = rid
                        break
        else:
            row = None
            source_id = None
            for rid in run_ids_by_priority:
                if test_id in run_results[rid]:
                    row = run_results[rid][test_id]
                    source_id = rid
                    break

        if row:
            details = json.loads(row["details"]) if row.get("details") else {}
            details["merged_from_run"] = source_id
            save_result(
                run_id=new_run_id,
                test_id=row["test_id"],
                category=row["category"],
                metric=row["metric"],
                prompt=row.get("prompt", ""),
                response=row.get("response", ""),
                score=row["score"],
                details=details,
            )

    return new_run_id


def delete_run(run_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM results WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))


def get_summary_by_run(run_id: int):
    with get_connection() as conn:
        return conn.execute(
            """SELECT category, metric, AVG(score) as avg_score, COUNT(*) as count
               FROM results WHERE run_id = ?
               GROUP BY category, metric""",
            (run_id,),
        ).fetchall()
