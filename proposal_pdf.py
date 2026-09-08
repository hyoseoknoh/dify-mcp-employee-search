"""DB에 저장된 후보자 자료를 일본어 PDF로 출력합니다."""

import argparse
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

import document_store

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "pdf"
LABELS = {
    "department": "所属部署", "nationality": "国籍", "task": "担当業務",
    "skills": "開発スキル", "skill": "開発スキル",
    "languages": "使用可能言語", "language": "使用可能言語",
    "certifications": "保有資格", "min_experience_years": "最低実務経験年数",
    "experience_years": "実務経験年数", "available_regions": "勤務可能地域",
    "available_from": "参加可能日",
}
FIELDS = ["department", "task", "skills", "experience_years", "languages",
          "certifications", "available_regions", "available_from"]


def register_font():
    # 日本語をPDFに埋め込みます。他のPCでは環境変数でTTFを指定できます。
    if "ProposalJP" in pdfmetrics.getRegisteredFontNames():
        return
    paths = [os.getenv("PROPOSAL_PDF_FONT", ""),
             "/Library/Fonts/Arial Unicode.ttf",
             "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    font = next((Path(p) for p in paths if p and Path(p).is_file()), None)
    if font is None:
        raise ValueError("日本語TTFフォントをPROPOSAL_PDF_FONTに指定してください。")
    pdfmetrics.registerFont(TTFont("ProposalJP", str(font)))


def display(value):
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value) or "未登録"
    if isinstance(value, dict):
        return " / ".join(f"{key}: {display(item)}" for key, item in value.items())
    return "未登録" if value is None or value == "" else str(value)


def export_proposal_pdf(proposal_id: int) -> dict:
    """保存済みスナップショットを出力。CSVの再検索やDBの変更は行いません。"""
    if isinstance(proposal_id, bool) or not isinstance(proposal_id, int) or proposal_id < 1:
        raise ValueError("資料番号は1以上の整数で指定してください。")
    proposal = document_store.get_proposal(proposal_id)
    candidates = proposal["candidates"]
    if not candidates:
        raise ValueError("候補者が0名のためPDFを作成できません。")
    register_font()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"proposal_{proposal_id}_{uuid4().hex[:12]}.pdf"
    body = ParagraphStyle("Body", fontName="ProposalJP", fontSize=9,
                          leading=14, wordWrap="CJK", alignment=TA_LEFT)
    heading = ParagraphStyle("Heading", parent=body, fontSize=14, leading=21,
                             spaceBefore=16, spaceAfter=8, keepWithNext=True,
                             textColor=colors.HexColor("#163B57"))
    title = ParagraphStyle("Title", parent=heading, fontSize=22, leading=30)

    def p(value, style=body):
        return Paragraph(escape(display(value)).replace("\n", "<br/>"), style)

    width = A4[0] - 36 * mm

    def table(rows):
        result = Table([[p(label), p(value)] for label, value in rows],
                       colWidths=[38 * mm, width - 38 * mm],
                       hAlign="LEFT", splitByRow=1, splitInRow=1)
        result.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EDF3F7")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6E0E7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return result

    story = [p(proposal["title"], title),
             p(f"資料番号: {proposal_id}  /  候補者数: {len(candidates)}名"),
             p(f"PDF作成日時: {datetime.now():%Y-%m-%d %H:%M}"),
             Spacer(1, 3 * mm),
             p("本資料はDBに保存された候補者情報をもとに作成しています。"),
             p("検索条件", heading)]
    conditions = [(LABELS.get(key, key), value)
                  for key, value in proposal["conditions"].items()
                  if value is not None and value != "" and value != []]
    story.append(table(conditions) if conditions else p("指定条件なし"))
    for index, person in enumerate(candidates, 1):
        story.append(p(f"{index:02d}  {person.get('name', '未登録')}", heading))
        rows = []
        for key in FIELDS:
            value = person.get(key)
            if key == "experience_years" and value is not None and value != "":
                value = f"{value}年"
            rows.append((LABELS[key], value))
        story.append(table(rows))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D6E0E7"))
        canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
        canvas.setFont("ProposalJP", 8)
        canvas.drawString(18 * mm, 11 * mm, f"候補者資料 / {proposal_id}")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18 * mm,
                            leftMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=23 * mm, title=proposal["title"])
    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"proposal_id": proposal_id, "candidate_count": len(candidates),
            "file_path": str(path), "filename": path.name}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="候補者資料をPDFに出力")
    parser.add_argument("proposal_id", type=int)
    args = parser.parse_args()
    print(export_proposal_pdf(args.proposal_id)["file_path"])
