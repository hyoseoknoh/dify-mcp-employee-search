import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# 이 Python 파일과 같은 폴더에 DB 파일을 저장합니다.
DB_PATH = Path(__file__).resolve().parent / "documents.db"


@contextmanager
def connect_database():
    """연결을 열고, 성공하면 저장하고, 오류가 나면 취소한 뒤 닫습니다."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    with connect_database() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS resumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_name TEXT NOT NULL UNIQUE,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                conditions_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS proposal_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id INTEGER NOT NULL,
                employee_name TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                FOREIGN KEY (proposal_id) REFERENCES proposals(id)
            );
        """)



def create_proposal(title: str, conditions: dict, candidates: list[dict]) -> int:
    """검색조건과 후보자 정보를 함께 저장하고 자료 번호를 반환합니다."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("자료 제목을 입력해 주세요.")
    if not isinstance(conditions, dict):
        raise ValueError("검색조건은 딕셔너리여야 합니다.")
    if not candidates:
        raise ValueError("저장할 후보자가 없습니다.")

    # 이름과 JSON을 먼저 확인해 잘못된 자료가 일부만 저장되지 않게 합니다.
    candidate_rows = []
    names = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("후보자 정보는 딕셔너리여야 합니다.")
        name = candidate.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("후보자의 name이 필요합니다.")
        name = name.strip()
        if name in names:
            raise ValueError(f"같은 후보자가 중복되었습니다: {name}")
        names.add(name)
        snapshot = dict(candidate, name=name)
        candidate_rows.append((name, json.dumps(snapshot, ensure_ascii=False)))

    with connect_database() as connection:
        cursor = connection.execute(
            "INSERT INTO proposals (title, conditions_json) VALUES (?, ?)",
            (title.strip(), json.dumps(conditions, ensure_ascii=False)),
        )
        proposal_id = cursor.lastrowid
        connection.executemany(
            """INSERT INTO proposal_candidates
               (proposal_id, employee_name, snapshot_json) VALUES (?, ?, ?)""",
            [(proposal_id, name, snapshot) for name, snapshot in candidate_rows],
        )
    return proposal_id


def get_proposal(proposal_id: int) -> dict:
    """자료 번호로 검색조건과 저장 당시의 후보자 정보를 불러옵니다."""
    with connect_database() as connection:
        proposal = connection.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if proposal is None:
            raise ValueError(f"자료 번호 {proposal_id}을 찾을 수 없습니다.")
        candidates = connection.execute(
            """SELECT snapshot_json FROM proposal_candidates
               WHERE proposal_id = ? ORDER BY id""", (proposal_id,)
        ).fetchall()

    return {
        "id": proposal["id"],
        "title": proposal["title"],
        "conditions": json.loads(proposal["conditions_json"]),
        "candidates": [json.loads(row["snapshot_json"]) for row in candidates],
        "created_at": proposal["created_at"],
        "updated_at": proposal["updated_at"],
    }


def remove_proposal_candidate(proposal_id: int, employee_name: str) -> bool:
    """자료에서만 후보자를 제외합니다. 원본 직원 데이터는 변경하지 않습니다."""
    with connect_database() as connection:
        proposal = connection.execute(
            "SELECT id FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if proposal is None:
            raise ValueError(f"자료 번호 {proposal_id}을 찾을 수 없습니다.")
        cursor = connection.execute(
            """DELETE FROM proposal_candidates
               WHERE proposal_id = ? AND employee_name = ?""",
            (proposal_id, employee_name.strip()),
        )
        removed = cursor.rowcount > 0
        if removed:
            connection.execute(
                "UPDATE proposals SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (proposal_id,),
            )
    return removed


if __name__ == "__main__":
    initialize_database()
    print(f"DB를 준비했습니다: {DB_PATH}")
