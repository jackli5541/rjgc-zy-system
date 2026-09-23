from __future__ import annotations

import csv
import io
from fastapi import APIRouter, Query, Response
from fastapi.responses import PlainTextResponse
from openpyxl import Workbook
from typing import Literal
from uuid import UUID

from app.core.deps import CurrentUser, Db, require_class, teacher
from app.core.utils import content_disposition
from app.modules.grades.service import export_cell, export_rows

router = APIRouter()

@router.get("/api/v1/exports/{kind}.csv")
def export_csv(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query(), assignment_id: UUID | None = Query(None)):
    teacher(user); require_class(db, user, class_id); out = io.StringIO(); writer = csv.writer(out); writer.writerows([[export_cell(value) for value in row] for row in export_rows(kind, class_id, user, db, assignment_id)])
    suffix = f"-{assignment_id}" if kind == "grades" else ""
    return PlainTextResponse("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{kind}{suffix}.csv"'})


@router.get("/api/v1/exports/{kind}.xlsx")
def export_xlsx(kind: Literal["members", "teams", "grades", "reviews"], user: CurrentUser, db: Db, class_id: UUID = Query(), assignment_id: UUID | None = Query(None)):
    teacher(user); require_class(db, user, class_id); workbook = Workbook(); sheet = workbook.active; sheet.title = "导出数据"
    for row in export_rows(kind, class_id, user, db, assignment_id): sheet.append([export_cell(value) for value in row])
    suffix = f"-{assignment_id}" if kind == "grades" else ""
    buffer = io.BytesIO(); workbook.save(buffer); buffer.seek(0)
    return Response(content=buffer.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": content_disposition(f"{kind}{suffix}.xlsx")})
