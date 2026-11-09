"""批改结果 Excel：模板生成与解析。不访问数据库，数据由调用方准备。"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

TEMPLATE_VERSION = "1"
SHEET_GRADE = "批改"
SHEET_FEEDBACK = "互评二次点评"
SHEET_META = "元信息"
MAX_ROWS = 2000

GRADE_HEADERS = ["作业ID", "version_id", "学号", "姓名", "提交时间", "教师等级", "作业点评", "互评概况", "状态"]
FEEDBACK_HEADERS = ["version_id", "assessment_id", "互评者", "互评等级", "互评原文", "针对", "二次点评类别", "二次点评内容"]

CATEGORY_LABELS = {"MISUNDERSTANDING": "理解有误", "INSUFFICIENT_BASIS": "评价依据不足", "INAPPROPRIATE_WORDING": "表述不当", "OTHER": "其他"}
TARGET_LABELS = {"GRADE": "评分", "COMMENT": "总体评语"}
_CATEGORY_LOOKUP = {**{key: key for key in CATEGORY_LABELS}, **{label: key for key, label in CATEGORY_LABELS.items()}}
_TARGET_LOOKUP = {**{key: key for key in TARGET_LABELS}, **{label: key for key, label in TARGET_LABELS.items()}}


def category_from_text(value: str) -> str | None:
    return _CATEGORY_LOOKUP.get(value.strip())


def target_from_text(value: str) -> str | None:
    value = value.strip()
    return _TARGET_LOOKUP.get(value) if value else "COMMENT"


def build_template(assignment_id: str, title: str, grade_rows: list[list[Any]], feedback_rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_GRADE
    ws.append(GRADE_HEADERS)
    for row in grade_rows:
        ws.append(row)
    fb = wb.create_sheet(SHEET_FEEDBACK)
    fb.append(FEEDBACK_HEADERS)
    for row in feedback_rows:
        fb.append(row)
    meta = wb.create_sheet(SHEET_META)
    meta.append(["template_version", TEMPLATE_VERSION])
    meta.append(["assignment_id", assignment_id])
    meta.append(["assignment_title", title])
    meta.append(["generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    meta.sheet_state = "hidden"

    head_fill = PatternFill("solid", fgColor="E8EEF7")
    for sheet, widths in ((ws, [38, 38, 14, 12, 18, 10, 60, 22, 12]), (fb, [38, 38, 14, 10, 50, 12, 16, 60])):
        for cell in sheet[1]:
            cell.font, cell.fill = Font(bold=True), head_fill
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[chr(64 + index)].width = width
        sheet.freeze_panes = "A2"
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    grades = DataValidation(type="list", formula1='"A,B,C,D,E"', allow_blank=True)
    ws.add_data_validation(grades)
    grades.add("F2:F2001")
    categories = DataValidation(type="list", formula1='"' + ",".join(CATEGORY_LABELS.values()) + '"', allow_blank=True)
    targets = DataValidation(type="list", formula1='"' + ",".join(TARGET_LABELS.values()) + '"', allow_blank=True)
    fb.add_data_validation(categories)
    fb.add_data_validation(targets)
    categories.add("G2:G2001")
    targets.add("F2:F2001")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _table(ws, headers: list[str], required: list[str]) -> list[dict[str, Any]]:
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        raise ValueError(f"「{ws.title}」是空表")
    names = [_text(item) for item in header]
    missing = [name for name in required if name not in names]
    if missing:
        raise ValueError(f"「{ws.title}」缺少列：{'、'.join(missing)}")
    result = []
    for number, values in enumerate(rows, 2):
        if number > MAX_ROWS + 1:
            raise ValueError(f"「{ws.title}」超过 {MAX_ROWS} 行")
        item = {name: _text(values[index]) if index < len(values) else "" for index, name in enumerate(names) if name}
        if any(item.values()):
            item["_row"] = number
            result.append(item)
    return result


def parse_workbook(content: bytes) -> dict:
    """解析上传的 Excel，返回 {meta, grades, feedbacks}；格式不对时抛 ValueError。"""
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("无法打开 Excel 文件，请确认是 .xlsx 格式") from exc
    if SHEET_GRADE not in wb.sheetnames:
        raise ValueError(f"缺少工作表「{SHEET_GRADE}」，请使用平台下载的模板")
    meta: dict[str, str] = {}
    if SHEET_META in wb.sheetnames:
        for row in wb[SHEET_META].iter_rows(values_only=True):
            if row and row[0]:
                meta[_text(row[0])] = _text(row[1] if len(row) > 1 else "")
    if meta.get("template_version") and meta["template_version"] != TEMPLATE_VERSION:
        raise ValueError("模板版本不匹配，请重新下载最新模板")
    grades = _table(wb[SHEET_GRADE], GRADE_HEADERS, ["version_id", "教师等级", "作业点评"])
    feedbacks = _table(wb[SHEET_FEEDBACK], FEEDBACK_HEADERS, ["version_id", "assessment_id", "二次点评类别", "二次点评内容"]) if SHEET_FEEDBACK in wb.sheetnames else []
    return {"meta": meta, "grades": grades, "feedbacks": feedbacks}
