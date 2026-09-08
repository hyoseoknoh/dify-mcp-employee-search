import csv
import json
import os
import re
import smtplib
from pathlib import Path
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from mcp.server import MCPServer


load_dotenv()

mcp = MCPServer("mail_MCP")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "employees.csv")
PROPOSAL_PDF_DIR = Path(BASE_DIR) / "output" / "pdf"
MAX_PDF_BYTES = 15 * 1024 * 1024

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = (
    os.getenv("GMAIL_APP_PASSWORD", "")
    .replace(" ", "")
    .strip()
)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PROJECT_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z0-9+#.\-]*)\s*(?:案件|안건)",
    re.IGNORECASE,
)


# ==================================================
# 입력 검증 및 제목 생성
# ==================================================

def is_valid_email(email: str) -> bool:
    """이메일 주소의 기본 형식을 확인합니다."""

    return bool(EMAIL_PATTERN.fullmatch((email or "").strip()))


def create_default_subject(body: str) -> str:
    """제목이 없을 때 메일 본문을 기준으로 간결한 제목을 생성합니다."""

    text = " ".join((body or "").split())

    # Java案件, Python 안건 등의 기술명을 제목에 활용합니다.
    match = PROJECT_PATTERN.search(text)
    if match:
        technology = match.group(1)
        return f"{technology}案件のご案内"

    if "案件" in text or "안건" in text:
        return "案件のご案内"

    return "ご連絡"


def normalize_name(value: str) -> str:
    """직원 이름의 앞뒤 및 연속 공백을 정리합니다."""

    return " ".join((value or "").strip().split())


def find_employee_email(name: str) -> tuple[str, str]:
    """CSV에서 직원 이름을 정확히 찾아 (이메일, 오류 메시지)를 반환합니다."""

    employee_name = normalize_name(name)
    if not employee_name:
        return "", "직원 이름을 입력해 주세요."

    if not os.path.isfile(CSV_FILE):
        return "", "employees.csv 파일을 찾을 수 없습니다."

    try:
        with open(CSV_FILE, "r", newline="", encoding="utf-8-sig") as file:
            matches = [
                row
                for row in csv.DictReader(file)
                if normalize_name(row.get("name", "")).casefold()
                == employee_name.casefold()
            ]
    except (OSError, csv.Error) as exc:
        return "", f"직원 CSV를 읽지 못했습니다: {exc}"

    if not matches:
        return "", f"{employee_name}의 직원 정보를 찾을 수 없습니다."

    if len(matches) > 1:
        return "", f"{employee_name} 이름의 직원이 여러 명이라 메일을 발송하지 않았습니다."

    email = (matches[0].get("email") or "").strip()
    if not is_valid_email(email):
        return "", f"{employee_name}의 올바른 이메일 주소가 등록되어 있지 않습니다."

    return email, ""


# ==================================================
# 내부 함수 - 이메일 주소로 메일 발송
# ==================================================

def _send_email(
    to_email: str,
    subject: str = "",
    body: str = "",
    attachment: tuple[str, bytes] | None = None,
) -> str:
    """
    지정된 이메일 주소로 메일을 발송하는 내부 함수입니다.

    Args:
        to_email: 수신자의 이메일 주소
        subject: 메일 제목. 비어 있으면 본문에서 자동 생성합니다.
        body: 메일 본문
    """

    if any(char in (to_email or "") + (subject or "") for char in "\r\n"):
        return "수신자 주소와 제목에는 줄바꿈을 넣을 수 없습니다."

    to_email = (to_email or "").strip()
    subject = (subject or "").strip()
    body = (body or "").strip()

    # ----------------------------------------------
    # 입력값 확인
    # ----------------------------------------------

    if not GMAIL_ADDRESS:
        return "메일 발송 계정이 설정되어 있지 않습니다."

    if not GMAIL_APP_PASSWORD:
        return "Gmail 앱 비밀번호가 설정되어 있지 않습니다."

    if not is_valid_email(to_email):
        return "올바른 수신자 이메일 주소를 입력해 주세요."

    if not body:
        return "메일 본문을 입력해 주세요."

    if not subject:
        subject = create_default_subject(body)

    # ----------------------------------------------
    # 메일 생성
    # ----------------------------------------------

    message = MIMEMultipart()
    message["From"] = GMAIL_ADDRESS
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))
    if attachment is not None:
        filename, data = attachment
        part = MIMEApplication(data, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(part)

    # ----------------------------------------------
    # Gmail SMTP를 이용해 발송
    # ----------------------------------------------

    try:
        with smtplib.SMTP(
            SMTP_HOST,
            SMTP_PORT,
            timeout=20,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD,
            )
            smtp.send_message(message)

        return (
            "메일 발송에 성공했습니다.\n"
            f"수신자: {to_email}\n"
            f"제목: {subject}"
        )

    except smtplib.SMTPAuthenticationError:
        return (
            "Gmail 인증에 실패했습니다. "
            "Gmail 주소와 앱 비밀번호를 확인해 주세요."
        )

    except smtplib.SMTPRecipientsRefused:
        return "수신자 이메일 주소가 Gmail 서버에서 거부되었습니다."

    except smtplib.SMTPException as exc:
        return f"메일 발송 중 SMTP 오류가 발생했습니다: {exc}"

    except (OSError, TimeoutError) as exc:
        return f"Gmail SMTP 서버 연결 중 오류가 발생했습니다: {exc}"

    except Exception as exc:
        return f"메일 발송 중 오류가 발생했습니다: {exc}"


@mcp.tool()
def send_employee_email(
    name: str,
    subject: str = "",
    body: str = "",
) -> str:
    """
    직원 이름으로 employees.csv에서 이메일을 찾은 뒤 메일을 발송합니다.

    Args:
        name: 메일을 받을 직원 이름
        subject: 메일 제목. 비어 있으면 본문에서 자동 생성합니다.
        body: 메일 본문
    """

    employee_name = normalize_name(name)
    email, error = find_employee_email(employee_name)
    if error:
        return error

    result = _send_email(
        to_email=email,
        subject=subject,
        body=body,
    )

    if result.startswith("메일 발송에 성공했습니다."):
        return (
            "메일 발송에 성공했습니다.\n"
            f"직원: {employee_name}\n"
            f"수신자: {email}\n"
            + "\n".join(result.splitlines()[2:])
        )

    return result


@mcp.tool()
def send_proposal_email(
    recipient_email: str,
    subject: str,
    body: str,
    attachment_filename: str,
) -> dict:
    """候補者PDFを指定された担当者のメールアドレスへ添付送信します。

    実際にメールを送る操作です。ユーザーが指定・承認した宛先と内容を使用してください。
    attachment_filenameにはexport_candidate_proposal_pdfが返すfilenameを渡します。
    絶対パスやURLは使用できません。output/pdf内のPDFを1つ添付します。
    SMTP受付後も実際の受信箱への配達は別途確認が必要です。
    """
    if not is_valid_email(recipient_email) or any(c in recipient_email for c in "\r\n"):
        return {"success": False, "message": "正しい宛先メールアドレスを指定してください。"}
    if not body.strip() or not subject.strip() or any(c in subject for c in "\r\n"):
        return {"success": False, "message": "本文と、改行を含まない件名を指定してください。"}

    # 指定フォルダのPDFだけを添付。../や絶対パス、外部を指すリンクは拒否します。
    filename = attachment_filename
    if (not filename or Path(filename).name != filename or
            any(c in filename for c in "/\\\r\n\x00") or
            Path(filename).suffix.lower() != ".pdf"):
        return {"success": False, "message": "PDFのファイル名だけを指定してください。"}
    try:
        root = PROPOSAL_PDF_DIR.resolve()
        path = (root / filename).resolve()
        if path.parent != root or not path.is_file():
            return {"success": False, "message": "指定されたPDFがoutput/pdf内にありません。"}
        with path.open("rb") as source:
            data = source.read(MAX_PDF_BYTES + 1)
        if len(data) > MAX_PDF_BYTES:
            return {"success": False, "message": "PDFは15MB以下にしてください。"}
        if not data.startswith(b"%PDF-"):
            return {"success": False, "message": "指定ファイルはPDF形式ではありません。"}
    except (OSError, ValueError, RuntimeError):
        return {"success": False, "message": "PDFファイルを読み込めませんでした。"}

    result = _send_email(recipient_email, subject, body, attachment=(filename, data))
    success = result.startswith("메일 발송에 성공했습니다.")
    return {
        "success": success,
        "status": "smtp_accepted" if success else "failed",
        "recipient_email": recipient_email.strip(),
        "attachment_filename": filename,
        "message": "PDF添付メールをSMTPサーバーへ送信しました。" if success else result,
    }


@mcp.tool()
def send_proposal_email_from_result(
    recipient_email: str,
    subject: str,
    body: str,
    pdf_result: dict | str,
) -> dict:
    """社員MCPのPDF作成結果を受け取り、生成されたPDFをメール送信します。

    pdf_resultにはcreate_candidate_proposal_pdfの返却値をそのまま渡せます。
    Dify側でPDFファイル名を抽出する必要はありません。
    """
    try:
        parsed_result = json.loads(pdf_result) if isinstance(pdf_result, str) else pdf_result
    except json.JSONDecodeError:
        return {"success": False, "message": "PDF作成結果をJSONとして読み取れませんでした。"}

    if not isinstance(parsed_result, dict):
        return {"success": False, "message": "PDF作成結果の形式が正しくありません。"}
    if not parsed_result.get("success"):
        return {
            "success": False,
            "message": parsed_result.get("message") or "PDF作成が完了していません。",
        }

    filename = parsed_result.get("filename")
    if not isinstance(filename, str) or not filename:
        return {"success": False, "message": "PDF作成結果にファイル名がありません。"}

    return send_proposal_email(
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        attachment_filename=filename,
    )


# ==================================================
# MCP Server 실행
# ==================================================

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8001,
        stateless_http=True,
        json_response=True,
    )
