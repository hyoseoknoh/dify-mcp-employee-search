import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

# ==================================================
# 이메일 주소 간단 검증
# ==================================================

def is_valid_email(email: str) -> bool:
    email = (email or "").strip()

    if not email:
        return False

    return "@" in email and "." in email.split("@")[-1]


# ==================================================
# MCP TOOL - 메일 발송
# ==================================================

@mcp.tool()
def send_email(
    to_email: str,
    subject: str,
    body: str,
) -> str:
    """
    지정된 이메일 주소로 메일을 발송합니다.

    Args:
        to_email: 수신자의 이메일 주소
        subject: 메일 제목
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

    if not subject:
        return "메일 제목을 입력해 주세요."

    if not body:
        return "메일 본문을 입력해 주세요."

    # ----------------------------------------------
    # 메일 생성
    # ----------------------------------------------

    message = MIMEMultipart()

    message["From"] = GMAIL_ADDRESS
    message["To"] = to_email
    message["Subject"] = subject

    message.attach(
        MIMEText(
            body,
            "plain",
            "utf-8",
        )
    )

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

    except smtplib.SMTPException as e:
        return f"메일 발송 중 SMTP 오류가 발생했습니다: {e}"

    except Exception as e:
        return f"메일 발송 중 오류가 발생했습니다: {e}"


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