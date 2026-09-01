import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from mcp.server import MCPServer


load_dotenv()

mcp = MCPServer("mail_MCP")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

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


# ==================================================
# MCP TOOL - 메일 발송
# ==================================================

@mcp.tool()
def send_email(
    to_email: str,
    subject: str = "",
    body: str = "",
) -> str:
    """
    지정된 이메일 주소로 메일을 발송합니다.

    Args:
        to_email: 수신자의 이메일 주소
        subject: 메일 제목. 비어 있으면 본문에서 자동 생성합니다.
        body: 메일 본문
    """

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
