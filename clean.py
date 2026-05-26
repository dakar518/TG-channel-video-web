import json, os

db = json.load(open('videos.json', encoding='utf-8'))
before = len(db['videos'])
db['videos'] = [v for v in db['videos'] if os.path.exists(v.get('file', ''))]
db['synced_ids'] = [v['id'] for v in db['videos']]
db['stats']['total'] = len(db['videos'])
open('videos.json', 'w', encoding='utf-8').write(
    json.dumps(db, ensure_ascii=False, indent=2)
)
print(f'?? {before - len(db["videos"])} ?????,?? {len(db["videos"])} ?')