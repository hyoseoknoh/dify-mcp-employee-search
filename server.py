from __future__ import annotations

import csv
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles


# ==================================================
# Basic settings
# ==================================================

mcp = MCPServer("test_MCP")

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
    nationality_key = clean_text(nationality).casefold()
    skills = skills or []
    languages = languages or []
    certifications = certifications or []
    available_regions = available_regions or []
    minimum = min_experience_years or 0

    results: list[dict[str, Any]] = []
    for row in read_rows():
        if department_key and department_key not in row["department"].casefold():
            continue
        if nationality_key and nationality_key != row["nationality"].casefold():
            continue
        if skills and not all(contains_value(row["skills"], item) for item in skills):
            continue
        if languages and not all(contains_value(row["languages"], item) for item in languages):
            continue
        if certifications and not all(
            contains_value(row["certifications"], item) for item in certifications
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


# ==================================================
# CREATE
# ==================================================

@mcp.tool()
def add_employee(
    name: str,
    department: str,
    task: str,
    nationality: str,
    skills: list[str] | str,
    languages: list[str] | str,
    certifications: list[str] | str = "",
    experience_years: int = 0,
    available_regions: list[str] | str = "",
    available_from: str = "",
    email: str = "",
    resume_file: str = "",
) -> dict[str, Any]:
    """직원 한 명을 CSV에 추가합니다. 목록 필드는 배열 또는 구분자 문자열을 받습니다."""

    try:
        cleaned_name = require_name(name)
        rows = read_rows()
        if any(name_key(row["name"]) == name_key(cleaned_name) for row in rows):
            return error_response(f"{cleaned_name} 이름의 직원이 이미 존재합니다.")

        row = {
            "name": cleaned_name,
            "department": clean_text(department),
            "task": clean_text(task),
            "nationality": clean_text(nationality),
            "skills": serialize_list(skills),
            "languages": serialize_list(languages),
            "certifications": serialize_list(certifications),
            "experience_years": parse_non_negative_int(experience_years, "실무경력"),
            "available_regions": serialize_list(available_regions),
            "available_from": validate_iso_date(available_from, "투입 가능일"),
            "email": validate_email(email),
            "resume_file": validate_resume_file(resume_file),
        }
        append_row(row)
        employee = employee_to_dict(row)
        message = f"{cleaned_name}님의 정보를 저장했습니다."
        return {"success": True, "employee": employee, "message": message}
    except EmployeeDataError as exc:
        return error_response(str(exc))


# ==================================================
# READ - exact normalized name
# ==================================================

@mcp.tool()
def get_employee(name: str) -> dict[str, Any]:
    """이름으로 직원을 찾고 구조화 데이터, email, 최종 표시 message를 반환합니다."""

    try:
        cleaned_name = require_name(name)
        matches = [
            employee_to_dict(row)
            for row in read_rows()
            if name_key(row["name"]) == name_key(cleaned_name)
        ]

        if not matches:
            message = f"{cleaned_name}の社員情報は見つかりませんでした。"
            return {
                "success": True,
                "found": False,
                "employee": None,
                "email": "",
                "message": message,
            }
        if len(matches) > 1:
            return error_response(
                f"{cleaned_name} 이름의 직원이 여러 명입니다. CSV의 중복 이름을 정리해 주세요."
            )

        employee = matches[0]
        return {
            "success": True,
            "found": True,
            "employee": employee,
            # Dify 메일 노드에서 깊은 경로 없이 바로 선택할 수 있게 최상위에도 둡니다.
            "email": employee["email"],
            "message": format_employee(employee),
        }
    except EmployeeDataError as exc:
        return error_response(str(exc))


# ==================================================
# READ - conditional search with skill fallback
# ==================================================

@mcp.tool()
def search_employee_data(
    department: str = "",
    nationality: str = "",
    skills: list[str] | str | None = None,
    languages: list[str] | str | None = None,
    certifications: list[str] | str | None = None,
    min_experience_years: int | None = None,
    available_regions: list[str] | str | None = None,
    available_from: str = "",
) -> dict[str, Any]:
    """조건 검색 결과를 구조화 데이터와 사용자 표시용 message로 반환합니다."""

    try:
        parsed_skills = parse_list(skills)
        parsed_languages = parse_list(languages)
        parsed_certifications = parse_list(certifications)
        parsed_regions = parse_list(available_regions)
        minimum = (
            None
            if min_experience_years is None
            else parse_non_negative_int(min_experience_years, "최소 실무경력")
        )
        requested_date = validate_iso_date(available_from, "요청 투입 가능일")

        criteria = {
            "department": clean_text(department),
            "nationality": clean_text(nationality),
            "skills": parsed_skills,
            "languages": parsed_languages,
            "certifications": parsed_certifications,
            "min_experience_years": minimum,
            "available_regions": parsed_regions,
            "available_from": requested_date,
        }

        employees = search_employees(
            department=criteria["department"],
            nationality=criteria["nationality"],
            skills=parsed_skills,
            languages=parsed_languages,
            certifications=parsed_certifications,
            min_experience_years=minimum,
            available_regions=parsed_regions,
            available_from=requested_date,
        )

        search_type = "exact"
        result_items: list[dict[str, Any]] = []

        if employees:
            result_items = [
                {**employee, "matched_skills": parsed_skills}
                for employee in employees
            ]
        elif len(parsed_skills) >= 2:
            candidates = search_employees(
                department=criteria["department"],
                nationality=criteria["nationality"],
                skills=[],
                languages=parsed_languages,
                certifications=parsed_certifications,
                min_experience_years=minimum,
                available_regions=parsed_regions,
                available_from=requested_date,
            )
            for employee in candidates:
                matched = [
                    skill
                    for skill in parsed_skills
                    if skill.casefold() in {item.casefold() for item in employee["skills"]}
                ]
                if matched:
                    result_items.append({**employee, "matched_skills": matched})

            result_items.sort(
                key=lambda item: (-len(item["matched_skills"]), item["name"].casefold())
            )
            if result_items:
                search_type = "partial_skills"

        if not result_items:
            message = "条件に一致する社員は見つかりませんでした。"
        else:
            heading = (
                f"条件に一致する社員が{len(result_items)}名見つかりました。"
                if search_type == "exact"
                else (
                    "完全一致する社員が見つからなかったため、"
                    f"一部のスキルが一致する社員を{len(result_items)}名表示します。"
                )
            )
            blocks = [
                format_employee(
                    employee,
                    employee["matched_skills"] if search_type == "partial_skills" else None,
                )
                for employee in result_items
            ]
            message = heading + "\n\n" + "\n\n---\n\n".join(blocks)

        return {
            "success": True,
            "search_type": search_type if result_items else "none",
            "count": len(result_items),
            "criteria": criteria,
            "employees": result_items,
            "message": message,
        }
    except EmployeeDataError as exc:
        return error_response(str(exc))


# ==================================================
# READ - all employees and resume file
# ==================================================

@mcp.tool()
def list_employees() -> dict[str, Any]:
    """전체 직원 목록을 구조화 데이터로 반환합니다."""

    try:
        employees = [employee_to_dict(row) for row in read_rows()]
        message = (
            "등록된 직원이 없습니다."
            if not employees
            else "등록 직원:\n" + "\n".join(f"- {item['name']}" for item in employees)
        )
        return {
            "success": True,
            "count": len(employees),
            "employees": employees,
            "message": message,
        }
    except EmployeeDataError as exc:
        return error_response(str(exc))


@mcp.tool()
def get_resume_file(name: str) -> dict[str, Any]:
    """직원 이름으로 이력서 파일명과 공개 URL을 반환합니다."""

    result = get_employee(name)
    if not result.get("success") or not result.get("found"):
        return result

    employee = result["employee"]
    resume_url = employee["resume_url"]
    message = (
        f"{employee['name']}님의 이력서: {format_resume_link(employee['resume_file'])}"
        if resume_url
        else f"{employee['name']}님에게 등록된 이력서가 없습니다."
    )
    return {
        "success": True,
        "found": bool(resume_url),
        "name": employee["name"],
        "resume_file": employee["resume_file"],
        "resume_url": resume_url,
        "message": message,
    }


# ==================================================
# UPDATE
# ==================================================

@mcp.tool()
def update_employee(
    name: str,
    new_name: str | None = None,
    department: str | None = None,
    task: str | None = None,
    nationality: str | None = None,
    skills: list[str] | str | None = None,
    languages: list[str] | str | None = None,
    certifications: list[str] | str | None = None,
    experience_years: int | None = None,
    available_regions: list[str] | str | None = None,
    available_from: str | None = None,
    email: str | None = None,
    resume_file: str | None = None,
) -> dict[str, Any]:
    """이름으로 직원을 찾아 전달된 필드만 수정합니다."""

    try:
        current_name = require_name(name)
        rows = read_rows()
        indexes = [
            index
            for index, row in enumerate(rows)
            if name_key(row["name"]) == name_key(current_name)
        ]
        if not indexes:
            return error_response(f"{current_name}님의 정보를 찾을 수 없습니다.")
        if len(indexes) > 1:
            return error_response(
                f"{current_name} 이름의 직원이 여러 명입니다. CSV의 중복 이름을 정리해 주세요."
            )

        index = indexes[0]
        row = rows[index]
        target_name = require_name(new_name) if new_name is not None else row["name"]
        if name_key(target_name) != name_key(row["name"]) and any(
            name_key(other["name"]) == name_key(target_name)
            for i, other in enumerate(rows)
            if i != index
        ):
            return error_response(f"{target_name} 이름의 직원이 이미 존재합니다.")

        updates: dict[str, Any] = {"name": target_name}
        for field, value in {
            "department": department,
            "task": task,
            "nationality": nationality,
        }.items():
            if value is not None:
                updates[field] = clean_text(value)

        for field, value in {
            "skills": skills,
            "languages": languages,
            "certifications": certifications,
            "available_regions": available_regions,
        }.items():
            if value is not None:
                updates[field] = serialize_list(value)

        if experience_years is not None:
            updates["experience_years"] = parse_non_negative_int(
                experience_years, "실무경력"
            )
        if available_from is not None:
            updates["available_from"] = validate_iso_date(available_from, "투입 가능일")
        if email is not None:
            updates["email"] = validate_email(email)
        if resume_file is not None:
            updates["resume_file"] = validate_resume_file(resume_file)

        row.update(updates)
        rows[index] = row
        write_rows(rows)
        employee = employee_to_dict(row)
        message = f"{current_name}님의 정보를 수정했습니다."
        return {"success": True, "employee": employee, "message": message}
    except EmployeeDataError as exc:
        return error_response(str(exc))


# ==================================================
# DELETE
# ==================================================

@mcp.tool()
def delete_employee(name: str) -> dict[str, Any]:
    """이름이 정확히 일치하는 직원 한 명을 삭제합니다."""

    try:
        cleaned_name = require_name(name)
        rows = read_rows()
        matches = [row for row in rows if name_key(row["name"]) == name_key(cleaned_name)]
        if not matches:
            return error_response(f"{cleaned_name}님의 정보를 찾을 수 없습니다.")
        if len(matches) > 1:
            return error_response(
                f"{cleaned_name} 이름의 직원이 여러 명이라 삭제하지 않았습니다."
            )

        remaining = [
            row for row in rows if name_key(row["name"]) != name_key(cleaned_name)
        ]
        write_rows(remaining)
        message = f"{matches[0]['name']}님의 정보를 삭제했습니다."
        return {
            "success": True,
            "deleted_employee": employee_to_dict(matches[0]),
            "message": message,
        }
    except EmployeeDataError as exc:
        return error_response(str(exc))


# ==================================================
# Dify-friendly text tools
# ==================================================

@mcp.tool()
def get_employee_message(name: str) -> str:
    """Dify 답변 노드에 바로 연결할 직원 상세정보 문자열을 반환합니다."""

    result = get_employee(name)
    return clean_text(result.get("message")) or "社員情報を取得できませんでした。"


@mcp.tool()
def get_employee_email(name: str) -> str:
    """Dify 메일 발송의 to_email에 바로 연결할 이메일 주소만 반환합니다."""

    result = get_employee(name)
    if not result.get("success") or not result.get("found"):
        # 오류 문구가 이메일 주소로 전달되어 발송되는 것을 막습니다.
        return ""
    return clean_text(result.get("email"))


def matched_requested_values(actual: list[str], requested: list[str]) -> list[str]:
    """실제 값 중 사용자가 요청한 값과 일치하는 항목만 반환합니다."""

    actual_by_key = {item.casefold(): item for item in actual}
    return [actual_by_key[item.casefold()] for item in requested if item.casefold() in actual_by_key]


def format_compact_search_employee(
    employee: dict[str, Any],
    criteria: dict[str, Any],
) -> str:
    """다수 검색 결과에서 이름과 실제 요청 조건만 간결하게 표시합니다."""

    lines = [f"名前: {employee['name']}"]

    if criteria.get("department"):
        lines.append(f"部署: {display_value(employee.get('department'))}")
    if criteria.get("nationality"):
        lines.append(f"国籍: {display_value(employee.get('nationality'))}")

    requested_skills = criteria.get("skills") or []
    if requested_skills:
        matched = employee.get("matched_skills") or matched_requested_values(
            employee.get("skills", []), requested_skills
        )
        lines.append(f"該当スキル: {display_value(matched)}")

    requested_languages = criteria.get("languages") or []
    if requested_languages:
        matched = matched_requested_values(employee.get("languages", []), requested_languages)
        lines.append(f"対応言語: {display_value(matched)}")

    requested_certifications = criteria.get("certifications") or []
    if requested_certifications:
        matched = matched_requested_values(
            employee.get("certifications", []), requested_certifications
        )
        lines.append(f"該当資格: {display_value(matched)}")

    # Dify가 경력 조건이 없는 경우 0을 전달하기도 하므로, 1년 이상일 때만 표시합니다.
    if (criteria.get("min_experience_years") or 0) > 0:
        lines.append(f"実務経験年数: {employee.get('experience_years', 0)}年")

    requested_regions = criteria.get("available_regions") or []
    if requested_regions:
        matched = matched_requested_values(
            employee.get("available_regions", []), requested_regions
        )
        lines.append(f"勤務可能地域: {display_value(matched)}")

    if criteria.get("available_from"):
        lines.append(f"参画可能日: {display_value(employee.get('available_from'))}")

    return "\n".join(lines)


@mcp.tool()
def search_employee_message(
    department: str = "",
    nationality: str = "",
    skills: list[str] | str | None = None,
    languages: list[str] | str | None = None,
    certifications: list[str] | str | None = None,
    min_experience_years: int | None = None,
    available_regions: list[str] | str | None = None,
    available_from: str = "",
) -> str:
    """Dify 답변 노드에 바로 연결할 직원 검색결과 문자열을 반환합니다."""

    result = search_employee_data(
        department=department,
        nationality=nationality,
        skills=skills,
        languages=languages,
        certifications=certifications,
        min_experience_years=min_experience_years,
        available_regions=available_regions,
        available_from=available_from,
    )
    if not result.get("success"):
        return clean_text(result.get("message")) or "社員検索結果を取得できませんでした。"

    employees = result.get("employees") or []
    if not employees:
        return clean_text(result.get("message")) or "条件に一致する社員は見つかりませんでした。"

    # 1名だけなら従来どおり詳細を表示します。
    if len(employees) == 1:
        return clean_text(result.get("message"))

    # 2名以上なら、氏名とユーザーが指定した条件だけを表示します。
    criteria = result.get("criteria") or {}
    heading = f"条件に一致する社員が{len(employees)}名見つかりました。"
    blocks = [format_compact_search_employee(employee, criteria) for employee in employees]
    return heading + "\n\n" + "\n\n".join(blocks)


# ==================================================
# Starlette / MCP Streamable HTTP / static PDF
# ==================================================

initialize_csv()

mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    host="0.0.0.0",
    transport_security=TRANSPORT_SECURITY,
)

app = Starlette(
    routes=[
        *mcp_app.routes,
        Mount("/pdf", app=StaticFiles(directory=str(PDF_DIR)), name="pdf"),
    ],
    lifespan=mcp_app.router.lifespan_context,
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
