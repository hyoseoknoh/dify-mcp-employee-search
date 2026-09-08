from __future__ import annotations

from typing import Any
import sqlite3

import document_store

from employee_core import (
    EmployeeDataError,
    append_row,
    clean_text,
    display_value,
    employee_to_dict,
    error_response,
    format_employee,
    format_resume_link,
    name_key,
    normalize_certification_query,
    normalize_name,
    parse_list,
    parse_non_negative_int,
    read_rows,
    require_name,
    search_employees,
    serialize_list,
    validate_email,
    validate_iso_date,
    validate_resume_file,
    write_rows,
)
from employee_mcp import mcp


@mcp.tool()
def export_candidate_proposal_pdf(proposal_id: int) -> dict[str, Any]:
    """保存済みの候補者資料番号からPDFを作成し、ローカルファイルの絶対パスを返します。
    除外済みの候補者は含めません。メール送信は行いません。
    返されるfile_pathはサーバーPC上のパスであり、ダウンロードURLではありません。
    """
    try:
        from proposal_pdf import export_proposal_pdf
        result = export_proposal_pdf(proposal_id)
        return {"success": True, **result,
                "message": f"候補者{result['candidate_count']}名のPDFを作成しました。"}
    except (ValueError, sqlite3.Error) as exc:
        return error_response(str(exc))
    except ImportError:
        return error_response("PDF用ライブラリがありません。プロジェクトでuv syncを実行してください。")
    except OSError:
        return error_response("PDFファイルを保存できませんでした。出力先を確認してください。")


@mcp.tool()
def create_candidate_proposal_pdf(
    title: str = "候補者一覧",
    department: str = "",
    nationality: str = "",
    skills: list[str] | str | None = None,
    languages: list[str] | str | None = None,
    certifications: list[str] | str | None = None,
    min_experience_years: int | None = None,
    available_regions: list[str] | str | None = None,
    available_from: str = "",
) -> dict[str, Any]:
    """社員検索、候補者資料のDB保存、PDF作成を一度に実行します。

    Difyから検索条件を受け取り、条件に一致した社員だけを資料として保存します。
    メール送信は行わず、メールMCPに渡すPDFファイル名を返します。
    """
    try:
        search_result = search_employee_data(
            department=department,
            nationality=nationality,
            skills=skills,
            languages=languages,
            certifications=certifications,
            min_experience_years=min_experience_years,
            available_regions=available_regions,
            available_from=available_from,
        )
        if not search_result.get("success"):
            return error_response(
                clean_text(search_result.get("message"))
                or "社員検索に失敗しました。"
            )

        candidates = search_result.get("employees") or []
        if not candidates:
            return error_response("条件に一致する社員がいないため、PDFを作成できませんでした。")

        document_store.initialize_database()
        proposal_id = document_store.create_proposal(
            clean_text(title) or "候補者一覧",
            search_result.get("criteria") or {},
            candidates,
        )

        from proposal_pdf import export_proposal_pdf

        pdf_result = export_proposal_pdf(proposal_id)
        return {
            "success": True,
            "proposal_id": proposal_id,
            "candidate_count": len(candidates),
            "filename": pdf_result["filename"],
            "file_path": pdf_result["file_path"],
            "message": (
                f"候補者{len(candidates)}名の資料を保存し、PDFを作成しました。"
                f"資料番号: {proposal_id}"
            ),
        }
    except (ValueError, EmployeeDataError, sqlite3.Error) as exc:
        return error_response(str(exc))
    except ImportError:
        return error_response("PDF用ライブラリがありません。プロジェクトでuv syncを実行してください。")
    except OSError:
        return error_response("PDFファイルを保存できませんでした。出力先を確認してください。")


@mcp.tool()
def create_candidate_proposal(
    title: str,
    conditions: dict[str, Any],
    employee_names: list[str] | str,
) -> dict[str, Any]:
    """検索した社員の名前一覧から候補者資料をDBに保存します。

    先にsearch_employee_data等で検索し、結果の正確な名前をemployee_namesに渡してください。
    employee_namesは配列またはカンマ区切りの文字列を受け付けます。
    conditionsは検索条件の記録です。このツール自体は条件検索しません。
    社員情報はCSVから取得します。PDF作成・メール送信は行いません。
    """
    try:
        parsed_employee_names = parse_list(employee_names)
        if not parsed_employee_names:
            raise ValueError("保存する社員名を指定してください。")
        rows = read_rows()
        candidates = []
        seen = set()
        for name in parsed_employee_names:
            cleaned_name = require_name(name)
            key = name_key(cleaned_name)
            if key in seen:
                raise ValueError(f"社員名が重複しています: {cleaned_name}")
            seen.add(key)
            matches = [row for row in rows if name_key(row["name"]) == key]
            if len(matches) != 1:
                raise ValueError(f"社員を一意に特定できません: {cleaned_name}")
            candidates.append(employee_to_dict(matches[0]))

        document_store.initialize_database()
        proposal_id = document_store.create_proposal(title, conditions, candidates)
        return {
            "success": True,
            "proposal_id": proposal_id,
            "candidate_count": len(candidates),
            "message": f"候補者{len(candidates)}名の資料を保存しました。資料番号: {proposal_id}",
        }
    except (ValueError, EmployeeDataError) as exc:
        return error_response(str(exc))
    except sqlite3.Error:
        return error_response("DBへの保存に失敗しました。DBの状態を確認してください。")


@mcp.tool()
def get_candidate_proposal(proposal_id: int) -> dict[str, Any]:
    """資料番号で、保存済みの検索条件と候補者情報を取得します。"""
    try:
        document_store.initialize_database()
        proposal = document_store.get_proposal(proposal_id)
        return {"success": True, "proposal": proposal}
    except ValueError as exc:
        return error_response(str(exc))
    except sqlite3.Error:
        return error_response("DBから資料を取得できませんでした。")


@mcp.tool()
def remove_candidate_from_proposal(
    proposal_id: int, employee_name: str
) -> dict[str, Any]:
    """指定された資料から社員1名を除外します。元の社員CSVは削除・変更しません。"""
    try:
        document_store.initialize_database()
        proposal = document_store.get_proposal(proposal_id)
        key = name_key(require_name(employee_name))
        matches = [person for person in proposal["candidates"]
                   if name_key(person["name"]) == key]
        if len(matches) != 1:
            raise ValueError("資料内の対象社員を一意に特定できません。")
        removed = document_store.remove_proposal_candidate(
            proposal_id, matches[0]["name"]
        )
        return {
            "success": removed,
            "proposal_id": proposal_id,
            "message": "候補者を資料から除外しました。" if removed else "候補者は既に除外されています。",
        }
    except (ValueError, EmployeeDataError) as exc:
        return error_response(str(exc))
    except sqlite3.Error:
        return error_response("DBの資料を更新できませんでした。")


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
def get_employee_message_from_query(query: str) -> str:
    """사용자 질문에서 등록된 직원 이름을 찾아 상세정보를 바로 반환합니다."""

    normalized_query = normalize_name(query)
    if not normalized_query:
        return "社員名を含む質問を入力してください。"

    try:
        rows = read_rows()
    except EmployeeDataError as exc:
        return str(exc)

    query_key = normalized_query.casefold()
    matched_names: list[str] = []
    seen: set[str] = set()

    # 긴 이름부터 확인하여 짧은 이름이 긴 이름의 일부인 경우를 줄입니다.
    names = sorted(
        (normalize_name(row.get("name")) for row in rows),
        key=len,
        reverse=True,
    )

    for employee_name in names:
        key = employee_name.casefold()

        # 문자나 숫자가 전혀 없는 값만 제외합니다. 'ノ' 같은 단일 문자 이름은 허용합니다.
        if not any(character.isalnum() for character in employee_name):
            continue

        if key in query_key and key not in seen:
            seen.add(key)
            matched_names.append(employee_name)

    if not matched_names:
        return "質問から登録済みの社員名を確認できませんでした。社員名を正確に入力してください。"

    if len(matched_names) > 1:
        names_text = "、".join(matched_names)
        return f"複数の社員名が含まれています: {names_text}。1名だけ指定してください。"

    return get_employee_message(matched_names[0])


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
        matched = [
            actual
            for actual in employee.get("certifications", [])
            if any(
                normalize_certification_query(requested) in actual.casefold()
                for requested in requested_certifications
                if normalize_certification_query(requested)
            )
        ]
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
    show_details: bool = False,
) -> str:
    """Dify 답변 노드에 바로 연결할 직원 검색결과 문자열을 반환합니다.

    show_details가 True이면 검색 인원수와 관계없이 전체 상세정보를 표시합니다.
    """

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

    # 사용자가 전체 상세정보를 요청했거나 결과가 1명이면 상세 표시합니다.
    if show_details or len(employees) == 1:
        return clean_text(result.get("message"))

    # 2名以上なら、氏名とユーザーが指定した条件だけを表示します。
    criteria = result.get("criteria") or {}
    heading = f"条件に一致する社員が{len(employees)}名見つかりました。"
    blocks = [format_compact_search_employee(employee, criteria) for employee in employees]
    return heading + "\n\n" + "\n\n".join(blocks)
