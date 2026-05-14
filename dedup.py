import json, os
from pathlib import Path

db = json.load(open('videos.json', encoding='utf-8'))
videos = db['videos']

# ?????+????,????
seen = {}
duplicates = []

for v in videos:
    key = f"{v.get('size_mb', 0)}_{v.get('duration', 0)}"
    if key in seen:
        duplicates.append(v)
        print(f"??: {v['file']} (? {seen[key]['file']} ??)")
    else:
        seen[key] = v

print(f"\n??? {len(duplicates)} ?????")

if duplicates:
    confirm = input("\n?????????(y/n): ")
    if confirm.lower() == 'y':
        for v in duplicates:
            # ????
            f = Path(v['file'])
            if f.exists():
                f.unlink()
                print(f"???: {v['file']}")
            # ?????
            thumb = Path('thumbs') / f"{f.stem}.jpg"
            if thumb.exists():
                thumb.unlink()

        # ?????
        keep_ids = set(v['id'] for v in videos if v not in duplicates)
        db['videos'] = [v for v in videos if v['id'] in keep_ids]
        db['synced_ids'] = [v['id'] for v in db['videos']]
        db['stats']['total'] = len(db['videos'])
        open('videos.json', 'w', encoding='utf-8').write(
            json.dumps(db, ensure_ascii=False, indent=2)
        )
        print(f"\n??!????: {len(db['videos'])} ?")
    else:
        print("???")
else:
    print("????????")