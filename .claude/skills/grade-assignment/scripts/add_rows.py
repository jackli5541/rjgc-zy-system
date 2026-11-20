# 给已有批改 Excel 补行（补交同学）。用法：python -I add_rows.py <xlsx> <new.json> <backup.xlsx>
# new.json: [{"assignment_id","version_id","student_no","name","submitted_at",
#             "peers":[{"assessment_id","reviewer","grade","text"}]}]
# 已存在的 version_id 会跳过，不改已批的行。
import json, sys, shutil, copy, openpyxl
xl, nj, backup = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copy(xl, backup)
rows = json.load(open(nj, encoding='utf-8'))
wb = openpyxl.load_workbook(xl)
ws, ws2 = wb['批改'], wb['互评二次点评']
have = {str(ws.cell(r, 2).value) for r in range(2, ws.max_row + 1)}
have_peer = {(str(ws2.cell(r, 1).value), str(ws2.cell(r, 2).value)) for r in range(2, ws2.max_row + 1)}

def clone_style(sheet, src, dst):
    for c in range(1, sheet.max_column + 1):
        s, d = sheet.cell(src, c), sheet.cell(dst, c)
        if s.has_style:
            d.font, d.border, d.fill = copy.copy(s.font), copy.copy(s.border), copy.copy(s.fill)
            d.alignment, d.number_format = copy.copy(s.alignment), s.number_format

added = skipped = peers = 0
for x in rows:
    if x['version_id'] in have:
        skipped += 1; continue
    r = ws.max_row + 1
    clone_style(ws, r - 1, r)
    for col, k in ((1, 'assignment_id'), (2, 'version_id'), (3, 'student_no'), (4, 'name'), (5, 'submitted_at')):
        ws.cell(r, col).value = x[k]
    ws.cell(r, 8).value = f"{len(x.get('peers', []))} 条互评"
    added += 1
    for p in x.get('peers', []):
        if (x['version_id'], p['assessment_id']) in have_peer:
            continue
        r2 = ws2.max_row + 1
        clone_style(ws2, r2 - 1, r2)
        for col, v in ((1, x['version_id']), (2, p['assessment_id']), (3, p['reviewer']), (4, p['grade']), (5, p['text'])):
            ws2.cell(r2, col).value = v
        peers += 1
wb.save(xl)
print('added', added, 'skipped(already in excel)', skipped, 'peer rows', peers)
