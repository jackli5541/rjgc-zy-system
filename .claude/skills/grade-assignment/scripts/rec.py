import json,sys,os
d=json.load(open(sys.argv[1],encoding='utf-8')); db=sys.argv[2]
res=json.load(open(db,encoding='utf-8')) if os.path.exists(db) else {}
res[d['v']]=d
json.dump(res,open(db,'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(len(res))
