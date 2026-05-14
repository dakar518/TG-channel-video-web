import json

db = json.load(open('videos.json', encoding='utf-8'))

# ?videos?????ID??synced_ids
all_ids = set(db.get('synced_ids', []))
for v in db['videos']:
    all_ids.add(v['id'])

db['synced_ids'] = list(all_ids)
open('videos.json', 'w', encoding='utf-8').write(
    json.dumps(db, ensure_ascii=False, indent=2)
)
print('????,??ID??:', len(db['synced_ids']))