"""가상 후보자와 임시 DB로 저장 → 조회 → 제외 과정을 확인합니다."""

import json
import tempfile
from pathlib import Path

import document_store as store


def main():
    original_path = store.DB_PATH
    try:
        # 실제 documents.db에 테스트 자료를 남기지 않습니다.
        with tempfile.TemporaryDirectory(prefix="proposal-demo-") as directory:
            store.DB_PATH = Path(directory) / "demo.db"
            store.initialize_database()

            proposal_id = store.create_proposal(
                title="Java案件向け候補者一覧（テスト）",
                conditions={"skill": "Java", "min_experience_years": 2,
                            "language": "日本語"},
                candidates=[
                    {"name": "テスト社員A", "skills": ["Java", "SQL"],
                     "experience_years": 3, "languages": ["日本語"]},
                    {"name": "テスト社員B", "skills": ["Java"],
                     "experience_years": 2, "languages": ["日本語", "英語"]},
                ],
            )
            before = store.get_proposal(proposal_id)
            assert len(before["candidates"]) == 2
            print(f"\n1. 후보자 두 명 저장 완료. 자료 번호: {proposal_id}")
            print(json.dumps(before, ensure_ascii=False, indent=2))

            assert store.remove_proposal_candidate(proposal_id, "テスト社員B")
            after = store.get_proposal(proposal_id)
            assert [person["name"] for person in after["candidates"]] == ["テスト社員A"]
            print("\n2. テスト社員B 제외 후 다시 조회")
            print(json.dumps(after, ensure_ascii=False, indent=2))

            assert not store.remove_proposal_candidate(proposal_id, "テスト社員B")
            try:
                store.get_proposal(proposal_id + 100)
            except ValueError:
                pass
            else:
                raise AssertionError("없는 자료 번호 검사 실패")

        print("\n확인 완료: 후보자 2명 → 1명. 실제 documents.db는 변경하지 않았습니다.")
    finally:
        store.DB_PATH = original_path


if __name__ == "__main__":
    main()
