"""DB에 저장된 후보자 자료를 일본어 PDF로 출력합니다."""

import argparse
import os
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
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
TABLE_COLUMNS = [
    ("No.", None, 8 * mm),
    ("氏名", "name", 26 * mm),
    ("部署", "department", 21 * mm),
    ("担当業務", "task", 29 * mm),
    ("国籍", "nationality", 18 * mm),
    ("スキル", "skills", 38 * mm),
    ("使用言語", "languages", 26 * mm),
    ("資格", "certifications", 25 * mm),
    ("経験年数", "experience_years", 17 * mm),
    ("勤務可能地域", "available_regions", 26 * mm),
    ("参画可能日", "available_from", 25 * mm),
]


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


def table_display(value):
    """一覧表向けに空欄と配列を短く表示します。"""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "なし"
    return "なし" if value is None or value == "" else str(value)


def format_condition_summary(conditions):
    parts = []
    for key, value in conditions.items():
        if value is None or value == "" or value == [] or value == 0:
            continue
        label = LABELS.get(key, key)
        shown = table_display(value)
        if key == "min_experience_years":
            shown = f"{shown}年以上"
        parts.append(f"{label} = {shown}")
    return " / ".join(parts) if parts else "指定条件なし"


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
                          leading=12, wordWrap="CJK", alignment=TA_LEFT)
    title = ParagraphStyle(
        "Title",
        parent=body,
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )
    meta = ParagraphStyle("Meta", parent=body, fontSize=9, leading=13)
    cell = ParagraphStyle("Cell", parent=body, fontSize=7.2, leading=9.2)
    header = ParagraphStyle(
        "Header",
        parent=cell,
        fontSize=7.4,
        leading=9.4,
        textColor=colors.white,
    )

    def p(value, style=body):
        return Paragraph(escape(display(value)).replace("\n", "<br/>"), style)

    def table_cell(value, style=cell):
        return Paragraph(escape(table_display(value)), style)

    rows = [[table_cell(label, header) for label, _, _ in TABLE_COLUMNS]]
    for index, person in enumerate(candidates, 1):
        row = []
        for _, key, _ in TABLE_COLUMNS:
            value = index if key is None else person.get(key)
            if key == "experience_years" and value is not None and value != "":
                value = f"{value}年"
            row.append(table_cell(value))
        rows.append(row)

    candidate_table = Table(
        rows,
        colWidths=[width for _, _, width in TABLE_COLUMNS],
        repeatRows=1,
        hAlign="CENTER",
        splitByRow=1,
    )
    table_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#355EA8")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A8A8A8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]
    for row_index in range(2, len(rows), 2):
        table_style.append(
            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F2F2F2"))
        )
    candidate_table.setStyle(TableStyle(table_style))

    story = [
        p(proposal["title"], title),
        p(f"資料番号: {proposal_id}", meta),
        p(f"検索条件: {format_condition_summary(proposal['conditions'])}", meta),
        p(f"候補者数: {len(candidates)}名", meta),
        Spacer(1, 5 * mm),
        candidate_table,
    ]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D6E0E7"))
        page_width = landscape(A4)[0]
        canvas.line(12 * mm, 10 * mm, page_width - 12 * mm, 10 * mm)
        canvas.setFont("ProposalJP", 8)
        canvas.drawString(12 * mm, 6 * mm, f"候補者資料 / {proposal_id}")
        canvas.drawRightString(page_width - 12 * mm, 6 * mm, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), rightMargin=12 * mm,
                            leftMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=15 * mm, title=proposal["title"])
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
