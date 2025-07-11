"""
ingest.py  —  YAML ➜ flattened SQLite
-------------------------------------
* One DB (content.db)
* Tables: file, problem
* Each question becomes one row in problem
"""
import json, uuid, yaml, sqlite3, pathlib
from typing import List, Dict, Any

# ───────────────────────── helpers ────────────────────────────────────────────
ROOT = pathlib.Path("/home/bot/bot/yk/YK/ROAR-Academy-main-output")
DB_PATH = ROOT / "metadata.db"


def gen_uuid() -> str:
    return str(uuid.uuid4())


def jdump(obj) -> str:  # compact helper
    return json.dumps(obj, ensure_ascii=False)


def load_yaml_dir(dir_: str | pathlib.Path) -> List[Dict]:
    """
    Recursively read every .yml/.yaml file, return a single list[dict].
    """
    out: List[Dict] = []
    for fp in pathlib.Path(dir_).rglob("*.yml"):
        out.extend(_load(fp))
    for fp in pathlib.Path(dir_).rglob("*.yaml"):
        out.extend(_load(fp))
    return out


def _load(path: pathlib.Path) -> List[Dict]:
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc if isinstance(doc, list) else [doc]


# ──────────────────── DB bootstrap (one file, two tables) ─────────────────────
if DB_PATH.exists():              # ❶   check for an old file
    DB_PATH.unlink()              # ❷   remove it
# now create a brand-new, empty DB on next connect
db = sqlite3.connect(DB_PATH)
with db:
    db.executescript(
        """
        /* file-level metadata ---------------------------------------------- */
        CREATE TABLE IF NOT EXISTS file (
            uuid       TEXT PRIMARY KEY,
            file_name  TEXT UNIQUE NOT NULL,
            url        TEXT,
            sections   TEXT              -- JSON blob
        );

        /* one row per question --------------------------------------------- */
        CREATE TABLE IF NOT EXISTS problem (
            uuid            TEXT PRIMARY KEY,
            file_uuid       TEXT,         -- FK → file(uuid)
            problem_index   REAL,
            problem_id      TEXT,
            problem_content TEXT,         -- optional raw stem/context
            question_id     INT,
            question        TEXT,
            choices         TEXT,         -- JSON list[str]
            answer          TEXT,         -- JSON list[int]
            explanation     TEXT
        );
        """
    )

# ─────────────────────────── ingestion logic ─────────────────────────────────
def ingest(files: List[Dict[str, Any]]) -> None:
    """
    files = list of top-level dicts (one per YAML 'file')
    Each dict may have 0..n 'problems'
    """
    for f in files:
        file_uuid = gen_uuid()

        db.execute(
            """
            INSERT INTO file (uuid, file_name, url, sections)
            VALUES (?, ?, ?, ?)
            """,
            (
                file_uuid,
                f["file_name"],
                f.get("URL"),
                jdump(f.get("sections")),
            ),
        )

        for pr in f.get("problems", {}):  # optional
            p_index = pr.get("problem_index")
            p_content = pr.get("problem_content")  # may be None
            p_id= pr.get("problem_id")  # e.g. "1.2.3" or "
            question_id=[1,2]
            # flatten every question under this problem ----------------------
            for id in question_id:
                q = pr["questions"][f'question_{id}']
                question_uuid = gen_uuid()

                db.execute(
                    """
                    INSERT INTO problem
                    (uuid, file_uuid, problem_index, problem_id,
                     problem_content,question_id, question, choices, answer, explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,?)
                    """,
                    (
                        question_uuid,
                        file_uuid,
                        p_index,
                        p_id,
                        p_content,
                        id,  # question_id
                        q.get("question"),
                        jdump(q.get("choices")),
                        jdump(q.get("answer")),  # list[int]
                        q.get("explanation"),
                    ),
                )

    db.commit()


# ───────────────────────────── CLI entrypoint ────────────────────────────────
if __name__ == "__main__":
    payload = load_yaml_dir("/home/bot/bot/yk/YK/ROAR-Academy-main")
    ingest(payload)
    print(f"✅ Imported {len(payload)} files and their questions into {DB_PATH}")
