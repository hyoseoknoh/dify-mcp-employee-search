from __future__ import annotations

import csv
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from mcp.server.transport_security import TransportSecuritySettings


# ==================================================
# Basic settings
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "employees.csv"
PDF_DIR = BASE_DIR / "pdf"

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://renewably-degraded-morale.ngrok-free.dev",
).strip().rstrip("/")

_public_url = urlparse(PUBLIC_BASE_URL)
NGROK_HOST = os.getenv("NGROK_HOST", _public_url.netloc).strip()

if not NGROK_HOST:
    raise RuntimeError("PUBLIC_BASE_URL 또는 NGROK_HOST를 올바르게 설정해 주세요.")

TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        NGROK_HOST,
        "localhost:*",
        "127.0.0.1:*",
    ],
    allowed_origins=[
        f"{_public_url.scheme or 'https'}://{NGROK_HOST}",
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
)

FIELDS = [
    "name",
    "department",
    "task",
    "nationality",
    "skills",
    "languages",
    "certifications",
    "experience_years",
    "available_regions",
    "available_from",
    "email",
    "resume_file",
]

LIST_FIELDS = {
    "skills",
    "languages",
    "certifications",
    "available_regions",
}

LIST_SEPARATOR_PATTERN = re.compile(r"[|,、，;；\n]+")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

NATIONALITY_ALIASES = {
    "한국": "韓国",
    "한국인": "韓国",
    "대한민국": "韓国",
    "韓国人": "韓国",
    "korea": "韓国",
    "korean": "韓国",
    "일본": "日本",
    "일본인": "日本",
    "日本人": "日本",
    "japan": "日本",
    "japanese": "日本",
    "중국": "中国",
    "중국인": "中国",
    "中国人": "中国",
    "china": "中国",
    "chinese": "中国",
    "대만": "台湾",
    "대만인": "台湾",
    "台湾人": "台湾",
    "taiwan": "台湾",
    "taiwanese": "台湾",
    "베트남": "ベトナム",
    "베트남인": "ベトナム",
    "越南": "ベトナム",
    "vietnam": "ベトナム",
    "vietnamese": "ベトナム",
    "인도": "インド",
    "인도인": "インド",
    "印度": "インド",
    "india": "インド",
    "indian": "インド",
    "필리핀": "フィリピン",
    "필리핀인": "フィリピン",
    "philippines": "フィリピン",
    "filipino": "フィリピン",
    "영국": "イギリス",
    "영국인": "イギリス",
    "英国": "イギリス",
    "uk": "イギリス",
    "british": "イギリス",
}


class EmployeeDataError(Exception):
    """직원 데이터 읽기/쓰기 또는 입력 검증 오류입니다."""


# ==================================================
# Validation and conversion helpers
# ==================================================

def clean_text(value: Any) -> str:
    """None을 빈 문자열로 바꾸고 앞뒤 공백을 제거합니다."""

    return "" if value is None else str(value).strip()


def normalize_name(value: Any) -> str:
    """이름의 앞뒤 공백과 연속 공백을 정리합니다."""

    return " ".join(clean_text(value).split())


def name_key(value: Any) -> str:
    """공백과 대소문자 차이를 무시하는 이름 비교 키를 만듭니다."""

    return normalize_name(value).casefold()


def require_name(value: Any) -> str:
    """비어 있지 않은 직원 이름을 반환합니다."""

    name = normalize_name(value)
    if not name:
        raise EmployeeDataError("직원 이름을 입력해 주세요.")
    return name


def parse_list(value: list[str] | str | None) -> list[str]:
    """Dify 배열 또는 구분자 문자열을 중복 없는 문자열 목록으로 바꿉니다."""

    if value is None:
        return []

    source = value if isinstance(value, list) else LIST_SEPARATOR_PATTERN.split(str(value))
    result: list[str] = []
    seen: set[str] = set()

    for item in source:
        # 배열 원소 안에 "Python|SQL"처럼 여러 값이 들어온 경우도 처리합니다.
        parts = LIST_SEPARATOR_PATTERN.split(str(item))
        for part in parts:
            cleaned = clean_text(part)
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                result.append(cleaned)

    return result


def serialize_list(value: list[str] | str | None) -> str:
    """목록을 기존 CSV와 호환되는 | 구분 문자열로 저장합니다."""

    return "|".join(parse_list(value))


def parse_non_negative_int(value: Any, field_name: str) -> int:
    """0 이상의 정수를 검증합니다."""

    try:
        number = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise EmployeeDataError(f"{field_name}은(는) 정수여야 합니다.") from exc

    if number < 0:
        raise EmployeeDataError(f"{field_name}은(는) 0 이상이어야 합니다.")
    return number


def parse_experience(value: Any) -> int:
    """CSV의 경력 값을 안전하게 정수로 변환합니다."""

    try:
        return max(0, int(clean_text(value) or 0))
    except ValueError:
        return 0


def normalize_nationality(value: Any) -> str:
    """한국어·일본어·영어의 국적 표현을 CSV의 대표 표기로 통일합니다."""

    text = clean_text(value)
    return NATIONALITY_ALIASES.get(text.casefold(), text)


def validate_iso_date(value: Any, field_name: str) -> str:
    """빈 값 또는 YYYY-MM-DD 날짜를 허용합니다."""

    text = clean_text(value)
    if not text:
        return ""

    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise EmployeeDataError(
            f"{field_name}은(는) YYYY-MM-DD 형식이어야 합니다."
        ) from exc
    return text


def validate_email(value: Any) -> str:
    """빈 값 또는 기본 형식에 맞는 이메일 주소를 허용합니다."""

    email = clean_text(value)
    if email and not EMAIL_PATTERN.fullmatch(email):
        raise EmployeeDataError("올바른 이메일 주소를 입력해 주세요.")
    return email


def validate_resume_file(value: Any) -> str:
    """pdf 폴더 밖을 가리킬 수 없는 파일명만 허용합니다."""

    filename = clean_text(value)
    if not filename:
        return ""
    if Path(filename).name != filename or filename in {".", ".."}:
        raise EmployeeDataError("이력서에는 경로를 제외한 파일명만 입력해 주세요.")
    return filename


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    """누락된 열이 있는 기존 CSV 행을 현재 스키마로 맞춥니다."""

    return {field: clean_text(row.get(field, "")) for field in FIELDS}


# ==================================================
# CSV initialization and I/O
# ==================================================

def initialize_csv() -> None:
    """PDF 폴더와 CSV를 만들고 기존 스키마를 현재 스키마로 확장합니다."""

    try:
        PDF_DIR.mkdir(parents=True, exist_ok=True)

        if not CSV_FILE.exists():
            with CSV_FILE.open("w", newline="", encoding="utf-8-sig") as file:
                csv.DictWriter(file, fieldnames=FIELDS).writeheader()
            return

        with CSV_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            current_fields = reader.fieldnames or []

        if current_fields == FIELDS:
            return

        # 기존 열의 값은 유지하고 새 열만 빈 값으로 보충합니다.
        write_rows([normalize_row(row) for row in rows])
    except (OSError, csv.Error) as exc:
        raise EmployeeDataError(f"직원 CSV 초기화에 실패했습니다: {exc}") from exc


def read_rows() -> list[dict[str, str]]:
    """모든 CSV 행을 현재 스키마로 읽습니다."""

    initialize_csv()
    try:
        with CSV_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            return [normalize_row(row) for row in csv.DictReader(file)]
    except (OSError, csv.Error) as exc:
        raise EmployeeDataError(f"직원 CSV를 읽지 못했습니다: {exc}") from exc


def write_rows(rows: list[dict[str, Any]]) -> None:
    """전체 행을 CSV에 기록합니다."""

    try:
        with CSV_FILE.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(normalize_row(row) for row in rows)
    except (OSError, csv.Error) as exc:
        raise EmployeeDataError(f"직원 CSV를 저장하지 못했습니다: {exc}") from exc


def append_row(row: dict[str, Any]) -> None:
    """한 행을 기존 CSV 뒤에 추가합니다."""

    initialize_csv()
    try:
        with CSV_FILE.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
            writer.writerow(normalize_row(row))
    except (OSError, csv.Error) as exc:
        raise EmployeeDataError(f"직원 정보를 저장하지 못했습니다: {exc}") from exc


# ==================================================
# Resume URL and employee representation
# ==================================================

def get_resume_url(resume_file: str) -> str:
    """이력서 파일의 외부 공개 URL을 만듭니다."""

    try:
        filename = validate_resume_file(resume_file)
    except EmployeeDataError:
        return ""

    return f"{PUBLIC_BASE_URL}/pdf/{quote(filename)}" if filename else ""


def format_resume_link(resume_file: str) -> str:
    """이력서 URL을 Markdown 링크로 만듭니다."""

    url = get_resume_url(resume_file)
    return f"[📄 履歴書を見る]({url})" if url else "登録された履歴書はありません"


def employee_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """CSV 행을 Dify가 바로 사용할 수 있는 구조화 객체로 변환합니다."""

    employee: dict[str, Any] = {
        "name": clean_text(row.get("name")),
        "department": clean_text(row.get("department")),
        "task": clean_text(row.get("task")),
        "nationality": clean_text(row.get("nationality")),
        "skills": parse_list(clean_text(row.get("skills"))),
        "languages": parse_list(clean_text(row.get("languages"))),
        "certifications": parse_list(clean_text(row.get("certifications"))),
        "experience_years": parse_experience(row.get("experience_years")),
        "available_regions": parse_list(clean_text(row.get("available_regions"))),
        "available_from": clean_text(row.get("available_from")),
        "email": clean_text(row.get("email")),
        "resume_file": clean_text(row.get("resume_file")),
        "resume_url": get_resume_url(clean_text(row.get("resume_file"))),
    }
    return employee


def display_value(value: Any, empty: str = "なし") -> str:
    """화면 표시용으로 목록과 빈 값을 정리합니다."""

    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else empty
    text = clean_text(value)
    return text or empty


def format_employee(employee: dict[str, Any], matched_skills: list[str] | None = None) -> str:
    """직원 객체를 최종 답변용 문자열로 만듭니다."""

    lines = [f"名前: {display_value(employee.get('name'))}"]
    if matched_skills is not None:
        lines.append(f"一致したスキル: {display_value(matched_skills)}")

    lines.extend(
        [
            f"部署: {display_value(employee.get('department'))}",
            f"担当業務: {display_value(employee.get('task'))}",
            f"国籍: {display_value(employee.get('nationality'))}",
            f"開発スキル: {display_value(employee.get('skills'))}",
            f"使用可能言語: {display_value(employee.get('languages'))}",
            f"保有資格: {display_value(employee.get('certifications'))}",
            f"実務経験年数: {employee.get('experience_years', 0)}年",
            f"勤務可能地域: {display_value(employee.get('available_regions'))}",
            f"参画可能日: {display_value(employee.get('available_from'))}",
            f"メール: {display_value(employee.get('email'))}",
            f"履歴書: {format_resume_link(clean_text(employee.get('resume_file')))}",
        ]
    )
    return "\n".join(lines)


def contains_value(csv_value: str, search_value: str) -> bool:
    """구분자 필드에 검색값이 정확히 포함되는지 확인합니다."""

    target = clean_text(search_value).casefold()
    return bool(target) and target in {item.casefold() for item in parse_list(csv_value)}


def normalize_certification_query(value: str) -> str:
    """'AWS資格', 'AWS 자격증' 같은 일반 표현에서 자격 관련 접미사를 제거합니다."""

    text = clean_text(value)
    text = re.sub(r"\s*(?:資格|認定資格|자격증|자격)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip().casefold()


def contains_certification(csv_value: str, search_value: str) -> bool:
    """자격증은 AWS → AWS SAA/AWS SAP처럼 계열명 부분 검색을 허용합니다."""

    target = normalize_certification_query(search_value)
    if not target:
        return False
    return any(target in item.casefold() for item in parse_list(csv_value))


def error_response(message: str) -> dict[str, Any]:
    """MCP 도구 공통 오류 응답입니다."""

    return {"success": False, "error": message, "message": message}


# ==================================================
# Common search logic
# ==================================================

def search_employees(
    department: str = "",
    nationality: str = "",
    skills: list[str] | None = None,
    languages: list[str] | None = None,
    certifications: list[str] | None = None,
    min_experience_years: int | None = None,
    available_regions: list[str] | None = None,
    available_from: str = "",
) -> list[dict[str, Any]]:
    """모든 전달 조건을 AND로 만족하는 직원을 반환합니다."""

    department_key = clean_text(department).casefold()
    nationality_key = normalize_nationality(nationality).casefold()
    skills = skills or []
    languages = languages or []
    certifications = certifications or []
    available_regions = available_regions or []
    minimum = min_experience_years or 0

    results: list[dict[str, Any]] = []
    for row in read_rows():
        if department_key and department_key not in row["department"].casefold():
            continue
        if (
            nationality_key
            and nationality_key != normalize_nationality(row["nationality"]).casefold()
        ):
            continue
        if skills and not all(contains_value(row["skills"], item) for item in skills):
            continue
        if languages and not all(contains_value(row["languages"], item) for item in languages):
            continue
        if certifications and not all(
            contains_certification(row["certifications"], item) for item in certifications
        ):
            continue
        if parse_experience(row["experience_years"]) < minimum:
            continue
        if available_regions and not all(
            contains_value(row["available_regions"], item) for item in available_regions
        ):
            continue
        # ISO 날짜이므로 문자열 순서와 날짜 순서가 같습니다.
        if available_from and row["available_from"] and row["available_from"] > available_from:
            continue

        results.append(employee_to_dict(row))

    return results



