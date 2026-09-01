import csv
import os
import re
from urllib.parse import quote

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles


# ==================================================
# 기본 설정
# ==================================================

mcp = MCPServer("test_MCP")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "employees.csv")
PDF_DIR = os.path.join(BASE_DIR, "pdf")


# ngrok을 다시 실행해 주소가 변경되면 수정해야 합니다.
PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://renewably-degraded-morale.ngrok-free.dev",
).rstrip("/")

NGROK_HOST = "renewably-degraded-morale.ngrok-free.dev"


TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        NGROK_HOST,
        "localhost:*",
        "127.0.0.1:*",
    ],
    allowed_origins=[
        f"https://{NGROK_HOST}",
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


# ==================================================
# CSV 초기화 및 기존 스키마 확장
# ==================================================

def initialize_csv():
    """PDF 폴더와 직원 CSV 파일을 초기화합니다."""

    os.makedirs(PDF_DIR, exist_ok=True)

    if not os.path.exists(CSV_FILE):
        with open(
            CSV_FILE,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()

        return

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        current_fields = reader.fieldnames or []

    if current_fields == FIELDS:
        return

    converted_rows = []

    for row in rows:
        converted_rows.append(
            {
                "name": row.get("name", ""),
                "department": row.get("department", ""),
                "task": row.get("task", ""),
                "nationality": row.get("nationality", ""),
                "skills": row.get("skills", ""),
                "languages": row.get("languages", ""),
                "certifications": row.get("certifications", ""),
                "experience_years": row.get(
                    "experience_years",
                    "",
                ),
                "available_regions": row.get(
                    "available_regions",
                    "",
                ),
                "available_from": row.get(
                    "available_from",
                    "",
                ),
                "email": row.get("email", ""),
                "resume_file": row.get("resume_file", ""),
            }
        )

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(converted_rows)


# ==================================================
# 이력서 URL 및 링크 생성
# ==================================================

def get_resume_url(resume_file: str) -> str:
    """이력서 파일의 외부 공개 URL을 만듭니다."""

    resume_file = (resume_file or "").strip()

    if not resume_file:
        return ""

    # pdf 폴더 밖의 경로 접근 방지
    safe_file_name = os.path.basename(resume_file)

    if safe_file_name != resume_file:
        return ""

    encoded_file_name = quote(safe_file_name)

    return f"{PUBLIC_BASE_URL}/pdf/{encoded_file_name}"


def format_resume_link(resume_file: str) -> str:
    """이력서 URL을 클릭 가능한 Markdown 링크로 만듭니다."""

    resume_url = get_resume_url(resume_file)

    if not resume_url:
        return "등록된 이력서 없음"

    return f"[📄 이력서 보기]({resume_url})"


# ==================================================
# 여러 값이 들어 있는 필드 검색
# ==================================================

def contains_value(csv_value: str, search_value: str) -> bool:
    """쉼표 또는 |로 구분된 여러 값을 검색합니다."""

    if not csv_value or not search_value:
        return False

    values = [
        value.strip().lower()
        for value in re.split(r"[|,、，]", csv_value)
        if value.strip()
    ]

    return search_value.strip().lower() in values


# ==================================================
# 직원 결과 포맷
# ==================================================

def format_employee(
    employee: dict,
    matched_skills: list[str] | None = None,
) -> str:
    """직원 정보를 MCP 응답용 문자열로 변환합니다."""

    resume_link = format_resume_link(
        employee.get("resume_file", "")
    )

    lines = [
        f"이름: {employee.get('name', '')}",
    ]

    if matched_skills is not None:
        lines.append(
            f"일치한 스킬: {', '.join(matched_skills)}"
        )

    lines.extend(
        [
            f"부서: {employee.get('department', '')}",
            f"업무: {employee.get('task', '')}",
            f"국적: {employee.get('nationality', '')}",
            f"개발 스킬: {employee.get('skills', '')}",
            f"사용 가능 언어: {employee.get('languages', '')}",
            f"자격증: {employee.get('certifications', '')}",
            f"실무경력: {employee.get('experience_years', '')}년",
            (
                "근무 가능 지역: "
                f"{employee.get('available_regions', '')}"
            ),
            (
                "투입 가능일: "
                f"{employee.get('available_from', '')}"
            ),
            f"이메일: {employee.get('email', '')}",
            f"이력서: {resume_link}",
        ]
    )

    return "\n".join(lines)


# ==================================================
# 공통 직원 검색
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
) -> list[dict]:

    initialize_csv()

    skills = skills or []
    languages = languages or []
    certifications = certifications or []
    available_regions = available_regions or []

    results = []

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:

            # ------------------------------------------
            # 부서
            # ------------------------------------------
            if department:
                if (
                    department.lower()
                    not in row.get(
                        "department",
                        "",
                    ).lower()
                ):
                    continue

            # ------------------------------------------
            # 국적
            # ------------------------------------------
            if nationality:
                if (
                    row.get(
                        "nationality",
                        "",
                    ).lower()
                    != nationality.lower()
                ):
                    continue

            # ------------------------------------------
            # 개발 스킬
            # 모든 지정 스킬을 만족해야 함 (AND)
            # ------------------------------------------
            if skills:
                if not all(
                    contains_value(
                        row.get("skills", ""),
                        skill,
                    )
                    for skill in skills
                ):
                    continue

            # ------------------------------------------
            # 사용 가능 언어
            # ------------------------------------------
            if languages:
                if not all(
                    contains_value(
                        row.get("languages", ""),
                        language,
                    )
                    for language in languages
                ):
                    continue

            # ------------------------------------------
            # 자격증
            # ------------------------------------------
            if certifications:
                if not all(
                    contains_value(
                        row.get("certifications", ""),
                        certification,
                    )
                    for certification in certifications
                ):
                    continue

            # ------------------------------------------
            # 최소 실무경력
            # ------------------------------------------
            if min_experience_years and min_experience_years > 0:
                try:
                    employee_experience = int(
                        row.get(
                            "experience_years",
                            "0",
                        )
                        or 0
                    )
                except ValueError:
                    employee_experience = 0

                if (
                    employee_experience
                    < min_experience_years
                ):
                    continue

            # ------------------------------------------
            # 근무 가능 지역
            # ------------------------------------------
            if available_regions:
                if not all(
                    contains_value(
                        row.get(
                            "available_regions",
                            "",
                        ),
                        region,
                    )
                    for region in available_regions
                ):
                    continue

            # ------------------------------------------
            # 투입 가능 시기
            # 직원의 투입 가능일이 요청 날짜보다 늦으면 제외
            # ------------------------------------------
            if available_from:
                employee_available_from = row.get(
                    "available_from",
                    "",
                )

                if (
                    employee_available_from
                    and employee_available_from
                    > available_from
                ):
                    continue

            results.append(
                {
                    "name": row.get("name", ""),
                    "department": row.get(
                        "department",
                        "",
                    ),
                    "task": row.get("task", ""),
                    "nationality": row.get(
                        "nationality",
                        "",
                    ),
                    "skills": row.get("skills", ""),
                    "languages": row.get(
                        "languages",
                        "",
                    ),
                    "certifications": row.get(
                        "certifications",
                        "",
                    ),
                    "experience_years": row.get(
                        "experience_years",
                        "",
                    ),
                    "available_regions": row.get(
                        "available_regions",
                        "",
                    ),
                    "available_from": row.get(
                        "available_from",
                        "",
                    ),
                    "email": row.get("email", ""),
                    "resume_file": row.get(
                        "resume_file",
                        "",
                    ),
                }
            )

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
    skills: str,
    languages: str,
    certifications: str = "",
    experience_years: int = 0,
    available_regions: str = "",
    available_from: str = "",
    email: str = "",
    resume_file: str = "",
) -> str:
    """
    직원 정보를 CSV 파일에 저장합니다.

    skills 예: Python|JavaScript|Java
    languages 예: 韓国語|日本語|英語
    certifications 예: AWS SAA|基本情報技術者
    available_regions 예: 東京|神奈川
    available_from 예: 2026-09-01
    """

    initialize_csv()

    resume_file = resume_file.strip()

    if (
        resume_file
        and os.path.basename(resume_file) != resume_file
    ):
        return (
            "이력서에는 경로를 제외한 "
            "파일명만 입력해 주세요."
        )

    with open(
        CSV_FILE,
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )

        writer.writerow(
            {
                "name": name,
                "department": department,
                "task": task,
                "nationality": nationality,
                "skills": skills,
                "languages": languages,
                "certifications": certifications,
                "experience_years": experience_years,
                "available_regions": available_regions,
                "available_from": available_from,
                "email": email,
                "resume_file": resume_file,
            }
        )

    return f"{name}님의 정보를 저장했습니다."


# ==================================================
# READ - 이름으로 검색
# ==================================================

@mcp.tool()
def get_employee(name: str) -> str:
    """이름으로 직원 정보를 검색합니다."""

    initialize_csv()

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            if row.get("name") == name:
                return format_employee(row)

    return f"{name}님의 정보를 찾을 수 없습니다."


# ==================================================
# READ - 조건 검색
# 정확 검색 → 스킬 부분 검색
# ==================================================

@mcp.tool()
def search_employee_data(
    department: str = "",
    nationality: str = "",
    skills: list[str] | None = None,
    languages: list[str] | None = None,
    certifications: list[str] | None = None,
    min_experience_years: int | None = None,
    available_regions: list[str] | None = None,
    available_from: str = "",
) -> str:
    """
    부서, 국적, 개발 스킬, 사용 가능 언어,
    자격증, 실무경력, 근무 가능 지역,
    투입 가능 시기를 기준으로 직원을 검색합니다.

    우선 모든 조건을 만족하는 직원을 검색합니다.

    정확히 일치하는 직원이 없고
    2개 이상의 스킬이 지정되어 있는 경우에는
    다른 검색 조건을 유지하면서
    요청 스킬 중 하나 이상을 보유한 직원을
    부분 일치 결과로 반환합니다.
    """

    skills = skills or []
    languages = languages or []
    certifications = certifications or []
    available_regions = available_regions or []

    # ==================================================
    # 1. 정확 검색
    # ==================================================

    employees = search_employees(
        department=department,
        nationality=nationality,
        skills=skills,
        languages=languages,
        certifications=certifications,
        min_experience_years=min_experience_years,
        available_regions=available_regions,
        available_from=available_from,
    )

    # ==================================================
    # 2. 정확 검색 성공
    # ==================================================

    if employees:
        formatted_employees = [
            format_employee(employee)
            for employee in employees
        ]

        return (
            "[검색 유형: 정확 일치]\n"
            + "\n\n".join(formatted_employees)
        )

    # ==================================================
    # 3. 정확 검색 실패
    #
    # 스킬이 2개 이상인 경우에만
    # 스킬 부분 일치 검색 수행
    #
    # 예:
    # Python AND Rust → 0명
    # Python OR Rust → 부분 일치 직원 검색
    #
    # 다른 검색 조건은 그대로 유지
    # ==================================================

    if len(skills) >= 2:

        # 스킬 조건만 제거한 상태로
        # 나머지 조건을 만족하는 직원 후보 검색
        candidates = search_employees(
            department=department,
            nationality=nationality,
            skills=[],
            languages=languages,
            certifications=certifications,
            min_experience_years=min_experience_years,
            available_regions=available_regions,
            available_from=available_from,
        )

        partial_results = []

        for employee in candidates:

            matched_skills = [
                skill
                for skill in skills
                if contains_value(
                    employee.get("skills", ""),
                    skill,
                )
            ]

            # 요청 스킬 중 아무것도 만족하지 않으면 제외
            if not matched_skills:
                continue

            partial_results.append(
                {
                    "employee": employee,
                    "matched_skills": matched_skills,
                }
            )

        # ==================================================
        # 일치한 스킬 수가 많은 직원을 우선 표시
        # ==================================================

        partial_results.sort(
            key=lambda item: len(
                item["matched_skills"]
            ),
            reverse=True,
        )

        # ==================================================
        # 부분 일치 결과 존재
        # ==================================================

        if partial_results:
            formatted_employees = []

            for item in partial_results:
                employee = item["employee"]
                matched_skills = item["matched_skills"]

                formatted_employees.append(
                    format_employee(
                        employee,
                        matched_skills=matched_skills,
                    )
                )

            return (
                "[검색 유형: 부분 일치]\n"
                f"요청한 스킬: {', '.join(skills)}\n"
                "모든 스킬 조건에 일치하는 직원은 "
                "없습니다.\n"
                "다만 일부 스킬 조건에 일치하는 "
                "직원이 있습니다.\n\n"
                + "\n\n".join(formatted_employees)
            )

    # ==================================================
    # 4. 부분 검색 결과도 없음
    # ==================================================

    return "조건에 해당하는 직원이 없습니다."


# ==================================================
# READ - 전체 직원
# ==================================================

@mcp.tool()
def list_employees() -> str:
    """저장된 모든 직원 정보를 조회합니다."""

    initialize_csv()

    employees = []

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            employees.append(
                format_employee(row)
            )

    if not employees:
        return "저장된 직원 정보가 없습니다."

    return "\n\n".join(employees)


# ==================================================
# READ - 이력서 파일 확인
# ==================================================

@mcp.tool()
def get_resume_file(name: str) -> str:
    """직원의 이력서 PDF 링크를 조회합니다."""

    initialize_csv()

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:

            if row.get("name") != name:
                continue

            resume_file = row.get(
                "resume_file",
                "",
            ).strip()

            if not resume_file:
                return (
                    f"{name}님의 이력서가 "
                    "등록되어 있지 않습니다."
                )

            safe_file_name = os.path.basename(
                resume_file
            )

            if safe_file_name != resume_file:
                return (
                    "올바르지 않은 "
                    "이력서 파일명입니다."
                )

            pdf_path = os.path.join(
                PDF_DIR,
                safe_file_name,
            )

            if not os.path.isfile(pdf_path):
                return (
                    f"{name}님의 이력서 파일을 "
                    "찾을 수 없습니다."
                )

            resume_url = get_resume_url(
                safe_file_name
            )

            return (
                f"이름: {name}\n"
                f"이력서 파일: {safe_file_name}\n"
                f"이력서: "
                f"[📄 이력서 보기]({resume_url})\n"
                f"이력서 URL: {resume_url}"
            )

    return f"{name}님의 정보를 찾을 수 없습니다."


# ==================================================
# UPDATE
# ==================================================

@mcp.tool()
def update_employee(
    name: str,
    department: str,
    task: str,
    nationality: str,
    skills: str,
    languages: str,
    certifications: str = "",
    experience_years: int = 0,
    available_regions: str = "",
    available_from: str = "",
    email: str = "",
    resume_file: str = "",
) -> str:
    """이름으로 직원을 찾아 정보를 수정합니다."""

    initialize_csv()

    resume_file = resume_file.strip()

    if (
        resume_file
        and os.path.basename(resume_file) != resume_file
    ):
        return (
            "이력서에는 경로를 제외한 "
            "파일명만 입력해 주세요."
        )

    employees = []
    updated = False

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:

            if row.get("name") == name and not updated:

                row["department"] = department
                row["task"] = task
                row["nationality"] = nationality
                row["skills"] = skills
                row["languages"] = languages
                row["certifications"] = certifications
                row["experience_years"] = str(
                    experience_years
                )
                row["available_regions"] = (
                    available_regions
                )
                row["available_from"] = available_from

                if email:
                    row["email"] = email

                if resume_file:
                    row["resume_file"] = resume_file

                updated = True

            employees.append(
                {
                    field: row.get(field, "")
                    for field in FIELDS
                }
            )

    if not updated:
        return f"{name}님의 정보를 찾을 수 없습니다."

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )
        writer.writeheader()
        writer.writerows(employees)

    return f"{name}님의 정보를 수정했습니다."


# ==================================================
# DELETE
# ==================================================

@mcp.tool()
def delete_employee(name: str) -> str:
    """이름으로 직원을 찾아 CSV 파일에서 삭제합니다."""

    initialize_csv()

    employees = []
    deleted = False

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:

            if row.get("name") == name and not deleted:
                deleted = True
                continue

            employees.append(
                {
                    field: row.get(field, "")
                    for field in FIELDS
                }
            )

    if not deleted:
        return f"{name}님의 정보를 찾을 수 없습니다."

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )
        writer.writeheader()
        writer.writerows(employees)

    return f"{name}님의 정보를 1건 삭제했습니다."


# ==================================================
# MCP와 PDF 서버 결합
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
        Mount(
            "/pdf",
            app=StaticFiles(
                directory=PDF_DIR
            ),
            name="pdf",
        ),
    ],
    lifespan=mcp_app.router.lifespan_context,
)


# ==================================================
# 서버 실행
# ==================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )