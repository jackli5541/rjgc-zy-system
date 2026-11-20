import json, sys, shutil, openpyxl
xl, db, backup = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copy(xl, backup)
d = json.load(open(db, encoding='utf-8'))
wb = openpyxl.load_workbook(xl)
ws = wb['批改']
vs = set(); done = set()
for r in range(2, ws.max_row+1):
    v = ws.cell(r,2).value
    if v: vs.add(str(v))
    if v in d:
        ws.cell(r,6).value = d[v]['grade']; ws.cell(r,7).value = d[v]['comment']; done.add(v)
print('students rows', len(vs), 'filled', len(done), 'missing in excel', [k for k in d if k not in vs])
print('excel not in db', [ (str(ws.cell(r,2).value), ws.cell(r,4).value, ws.cell(r,9).value) for r in range(2,ws.max_row+1) if ws.cell(r,2).value not in d])
ws2 = wb['互评二次点评']
keys = {}
for r in range(2, ws2.max_row+1):
    keys[(str(ws2.cell(r,1).value), str(ws2.cell(r,2).value))] = r
n=0; bad=[]
for v, rec in d.items():
    for p in rec['peer']:
        k=(v,p['aid'])
        if k in keys:
            r=keys[k]; ws2.cell(r,6).value=p['target']; ws2.cell(r,7).value=p['cat']; ws2.cell(r,8).value=p['text']; n+=1
        else: bad.append((rec['v'][:8], p['reviewer'], p['aid']))
print('peer filled', n, 'bad', bad)
wb.save(xl)
