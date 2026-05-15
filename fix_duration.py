import json, subprocess
from pathlib import Path

DB_FILE   = Path("videos.json")
VIDEO_DIR = Path("videos")

def get_duration(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except:
        return 0.0

def format_dur(sec):
    sec = int(sec)
    s = sec % 60
    m = (sec // 60) % 60
    h = sec // 3600
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

db = json.loads(DB_FILE.read_text(encoding="utf-8"))
total = len(db["videos"])

for i, v in enumerate(db["videos"]):
    if v.get("duration", 0) == 0 or v.get("duration_str", "0:00") == "0:00":
        f = Path(v["file"])
        if f.exists():
            dur = get_duration(f)
            v["duration"]     = dur
            v["duration_str"] = format_dur(dur)
            print(f"[{i+1}/{total}] {f.name} ? {v['duration_str']}")

tmp = DB_FILE.with_suffix(".tmp")
tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(DB_FILE)
print(f"\n? ??,??? {total} ???")