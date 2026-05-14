c = open('tg_sync.py', encoding='utf-8').read()

old = 'def already_downloaded(db: dict, msg_id: int, group: str) -> bool:\n    return f"{group}:{msg_id}" in db.get("synced_ids", [])'

new = '''def already_downloaded(db: dict, msg_id: int, group: str) -> bool:
    ids = db.get("synced_ids", [])
    return any(str(msg_id) in sid for sid in ids)'''

if old in c:
    c = c.replace(old, new)
    open('tg_sync.py', 'w', encoding='utf-8').write(c)
    print('????')
else:
    print('???????,?????')