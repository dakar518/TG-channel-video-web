#!/usr/bin/env python3
"""
TelegramVideoSync — 自动下载 Telegram 群组视频并生成 JSON 素材库
- 保留后台手动设置的分类、标签、标题、播放数、点赞数
- 新同步视频自动归入 NEW_VIDEO_CAT 分类
- 每次同步完成后自动扫描本地目录重建完整数据库
- 自动去重

依赖: pip install telethon aiofiles python-dotenv
用法: python3 tg_sync.py
"""

import os, json, asyncio, hashlib, logging, subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("TGSync")

# ── 配置 ─────────────────────────────────────────────────────────────────────
API_ID       = int(os.getenv("TG_API_ID", "0"))
API_HASH     = os.getenv("TG_API_HASH", "")
PHONE        = os.getenv("TG_PHONE", "")
SESSION_NAME = os.getenv("TG_SESSION", "tg_session")
WATCH_GROUPS = os.getenv("TG_GROUPS", "").split(",")
VIDEO_DIR    = Path(os.getenv("VIDEO_DIR", "videos"))
DB_FILE      = Path(os.getenv("DB_FILE",   "videos.json"))
MAX_FILE_MB  = int(os.getenv("MAX_FILE_MB", "500"))
MIN_DURATION = int(os.getenv("MIN_DURATION", "5"))

# 新同步视频自动归入此分类（可在 .env 中修改）
NEW_VIDEO_CAT = os.getenv("NEW_VIDEO_CAT", "最新同步")

VIDEO_DIR.mkdir(exist_ok=True)

# ── 数据库 ────────────────────────────────────────────────────────────────────
def load_db() -> dict:
    if DB_FILE.exists():
        try:
            content = DB_FILE.read_text(encoding="utf-8").strip()
            if content:
                return json.loads(content)
        except Exception:
            pass
    return {"videos": [], "synced_ids": [], "stats": {"total": 0, "today": 0, "groups": []}}

def save_db(db: dict):
    # 先写临时文件再替换，防止读写冲突导致文件为空
    tmp = DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_FILE)

def already_downloaded(db: dict, msg_id: int, group: str) -> bool:
    # 同时检查两种格式，防止群组名和数字ID不匹配
    ids = db.get("synced_ids", [])
    return any(str(msg_id) in sid for sid in ids)

def mark_downloaded(db: dict, msg_id: int, group: str):
    key = f"{group}:{msg_id}"
    if key not in db["synced_ids"]:
        db["synced_ids"].append(key)

def get_existing_entry(db: dict, video_id: str):
    """获取已有视频记录，用于保留手动设置的字段"""
    return next((v for v in db.get("videos", []) if v.get("id") == video_id), None)

def get_existing_by_file(db: dict, rel_path: str):
    """按文件路径查找已有记录"""
    return next((v for v in db.get("videos", []) if v.get("file") == rel_path), None)

# ── 视频工具 ──────────────────────────────────────────────────────────────────
def get_video_attr(doc):
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeVideo):
            return {"duration": attr.duration, "width": attr.w, "height": attr.h}
    return None

def format_dur(sec) -> str:
    sec = int(sec)
    s = sec % 60
    m = (sec // 60) % 60
    h = sec // 3600
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def make_thumb_url(file_path: str) -> str:
    return f"/thumbs/{Path(file_path).stem}.jpg"

def ffprobe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except:
        return 0.0

def ffprobe_dimensions(path: Path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10
        )
        s = json.loads(r.stdout)["streams"][0]
        return s.get("width", 0), s.get("height", 0)
    except:
        return 0, 0

# ── 重建数据库（扫描本地目录，保留手动设置）─────────────────────────────────
def rebuild_db():
    log.info("🔍 扫描本地视频目录，重建数据库（保留分类/标签）...")

    # 保留所有已有记录（包含手动设置的分类、标签、标题等）
    existing_by_file = {}
    existing_by_id   = {}
    if DB_FILE.exists():
        try:
            old = json.loads(DB_FILE.read_text(encoding="utf-8").strip())
            for v in old.get("videos", []):
                if v.get("file"):
                    existing_by_file[v["file"]] = v
                if v.get("id"):
                    existing_by_id[v["id"]] = v
            log.info(f"读取已有记录: {len(existing_by_file)} 条")
        except:
            pass

    # 扫描所有视频文件
    files = []
    for ext in ["*.mp4", "*.mov", "*.avi", "*.mkv"]:
        files.extend(sorted(VIDEO_DIR.glob(ext)))

    log.info(f"发现视频文件: {len(files)} 个")

    videos = []
    for i, f in enumerate(files):
        rel_path = f"videos/{f.name}"
        log.info(f"[{i+1}/{len(files)}] {f.name}")

        # ── 已有记录：完整保留手动设置的所有字段 ──
        if rel_path in existing_by_file:
            entry = existing_by_file[rel_path].copy()
            entry["thumb"] = make_thumb_url(rel_path)  # 更新缩略图路径
            # 确保关键字段存在，不强制覆盖
            entry.setdefault("cat",   "")
            entry.setdefault("tags",  [])
            entry.setdefault("views", 0)
            entry.setdefault("likes", 0)
            entry.setdefault("title", f.name)
            videos.append(entry)
            continue

        # ── 新文件：获取元数据，归入新同步分类 ──
        duration      = ffprobe_duration(f)
        width, height = ffprobe_dimensions(f)
        size_mb       = round(f.stat().st_size / 1024 / 1024, 2)
        mtime         = datetime.fromtimestamp(f.stat().st_mtime).isoformat()

        entry = {
            "id":           f"local:{f.stem}",
            "file":         rel_path,
            "thumb":        make_thumb_url(rel_path),
            "title":        f.name,
            "group":        "Telegram",
            "group_id":     "local",
            "cat":          NEW_VIDEO_CAT,   # 新视频归入新同步分类
            "duration":     duration,
            "duration_str": format_dur(duration),
            "width":        width,
            "height":       height,
            "size_mb":      size_mb,
            "mime":         "video/mp4",
            "views":        0,
            "likes":        0,
            "tags":         [],
            "date":         mtime,
            "synced_at":    mtime,
        }
        videos.append(entry)

    # 按时间排序，最新在前
    videos.sort(key=lambda v: v.get("synced_at", ""), reverse=True)

    db = {
        "videos":     videos,
        "synced_ids": [v["id"] for v in videos],
        "stats": {
            "total":  len(videos),
            "today":  0,
            "groups": list(set(v.get("group", "") for v in videos if v.get("group"))),
        }
    }
    save_db(db)
    log.info(f"✅ 数据库重建完成，共 {len(videos)} 条视频")
    return db

# ── 生成缩略图 ────────────────────────────────────────────────────────────────
def generate_thumbs():
    thumb_dir = Path("thumbs")
    thumb_dir.mkdir(exist_ok=True)
    files = []
    for ext in ["*.mp4", "*.mov"]:
        files.extend(VIDEO_DIR.glob(ext))
    count = 0
    log.info(f"🖼️  检查缩略图，共 {len(files)} 个文件...")
    for f in files:
        thumb = thumb_dir / f"{f.stem}.jpg"
        if not thumb.exists():
            try:
                subprocess.run(
                    ["ffmpeg", "-i", str(f), "-ss", "00:00:01",
                     "-vframes", "1", "-q:v", "2", str(thumb), "-y"],
                    capture_output=True, timeout=30
                )
                count += 1
            except Exception as e:
                log.warning(f"缩略图失败 {f.name}: {e}")
    log.info(f"🖼️  新增缩略图 {count} 张")

def make_thumb(out_path: Path):
    thumb = Path("thumbs") / f"{out_path.stem}.jpg"
    if not thumb.exists():
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(out_path), "-ss", "00:00:01",
                 "-vframes", "1", "-q:v", "2", str(thumb), "-y"],
                capture_output=True, timeout=30
            )
        except:
            pass

# ── 自动去重 ──────────────────────────────────────────────────────────────────
def dedup_videos():
    log.info("🔍 开始检查重复视频...")
    db = load_db()
    videos = db["videos"]
    seen = {}
    duplicates = []
    for v in videos:
        key = f"{v.get('size_mb', 0)}_{v.get('duration', 0)}"
        if key in seen:
            duplicates.append(v)
        else:
            seen[key] = v
    if not duplicates:
        log.info("✅ 没有发现重复视频")
        return
    log.info(f"发现 {len(duplicates)} 个重复视频，开始删除...")
    for v in duplicates:
        f = Path(v["file"])
        if f.exists():
            f.unlink()
            log.info(f"已删除: {v['file']}")
        thumb = Path("thumbs") / f"{f.stem}.jpg"
        if thumb.exists():
            thumb.unlink()
    keep_ids = set(v["id"] for v in videos if v not in duplicates)
    db["videos"]     = [v for v in videos if v["id"] in keep_ids]
    db["synced_ids"] = [v["id"] for v in db["videos"]]
    db["stats"]["total"] = len(db["videos"])
    save_db(db)
    log.info(f"✅ 去重完成，剩余视频: {len(db['videos'])} 个")

# ── Telegram 同步核心 ─────────────────────────────────────────────────────────
async def sync_group(client: TelegramClient, group: str, db: dict, limit: int = 50):
    log.info(f"开始同步群组: {group}")
    try:
        entity = await client.get_entity(group)
    except Exception as e:
        log.error(f"无法获取群组 {group}: {e}")
        return

    group_name = getattr(entity, "title", group)
    if group_name not in db["stats"]["groups"]:
        db["stats"]["groups"].append(group_name)

    downloaded = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if not msg.media or not isinstance(msg.media, MessageMediaDocument):
            continue
        doc = msg.media.document
        if not doc.mime_type.startswith("video/"):
            continue

        size_mb = doc.size / 1024 / 1024
        if size_mb > MAX_FILE_MB:
            continue

        attr = get_video_attr(doc)
        if not attr or attr["duration"] < MIN_DURATION:
            continue

        if already_downloaded(db, msg.id, group):
            continue

        ext       = doc.mime_type.split("/")[-1].replace("quicktime", "mov")
        file_hash = hashlib.md5(f"{group}:{msg.id}".encode()).hexdigest()[:8]
        filename  = f"{file_hash}_{msg.id}.{ext}"
        out_path  = VIDEO_DIR / filename
        video_id  = f"{group}:{msg.id}"

        log.info(f"下载: {filename} ({size_mb:.1f}MB, {format_dur(attr['duration'])})")
        try:
            await client.download_media(msg, str(out_path))
        except Exception as e:
            log.error(f"下载失败 msg_id={msg.id}: {e}")
            continue

        make_thumb(out_path)

        # ── 保留已有记录的手动设置字段 ──
        existing = get_existing_entry(db, video_id)
        caption  = (msg.text or "").strip()

        entry = {
            "id":           video_id,
            "file":         f"videos/{filename}",
            "thumb":        make_thumb_url(f"videos/{filename}"),
            # 已有记录保留原标题，新视频用 caption 或文件名
            "title":        existing.get("title") if existing else (caption[:120] if caption else filename),
            "group":        group_name,
            "group_id":     group,
            # 已有记录保留原分类，新视频归入 NEW_VIDEO_CAT
            "cat":          existing.get("cat") if existing and existing.get("cat") else NEW_VIDEO_CAT,
            "duration":     attr["duration"],
            "duration_str": format_dur(attr["duration"]),
            "width":        attr["width"],
            "height":       attr["height"],
            "size_mb":      round(size_mb, 2),
            "mime":         doc.mime_type,
            # 保留已有的播放数和点赞数
            "views":        existing.get("views", 0) if existing else 0,
            "likes":        existing.get("likes", 0) if existing else 0,
            # 保留已有标签，新视频为空
            "tags":         existing.get("tags", []) if existing else [],
            "date":         msg.date.isoformat() if msg.date else datetime.utcnow().isoformat(),
            "synced_at":    datetime.utcnow().isoformat(),
        }

        # 如果已存在则更新，否则插入到最前面
        existing_idx = next((i for i, v in enumerate(db["videos"]) if v.get("id") == video_id), None)
        if existing_idx is not None:
            db["videos"][existing_idx] = entry
        else:
            db["videos"].insert(0, entry)

        mark_downloaded(db, msg.id, group)
        db["stats"]["total"] = len(db["videos"])
        downloaded += 1
        save_db(db)

    log.info(f"群组 {group_name} 同步完成，本次新增 {downloaded} 个视频")

# ── 实时监听 ──────────────────────────────────────────────────────────────────
def register_realtime(client: TelegramClient, db: dict):
    @client.on(events.NewMessage(chats=WATCH_GROUPS))
    async def handler(event):
        msg = event.message
        if not msg.media or not isinstance(msg.media, MessageMediaDocument):
            return
        doc = msg.media.document
        if not doc.mime_type.startswith("video/"):
            return
        group = str(event.chat_id)
        if already_downloaded(db, msg.id, group):
            return
        log.info(f"实时收到新视频 from {group}, msg_id={msg.id}")
        asyncio.ensure_future(_download_one(client, msg, doc, group, db))

async def _download_one(client, msg, doc, group, db):
    attr = get_video_attr(doc)
    if not attr or attr["duration"] < MIN_DURATION:
        return
    size_mb = doc.size / 1024 / 1024
    if size_mb > MAX_FILE_MB:
        return

    ext      = doc.mime_type.split("/")[-1]
    h        = hashlib.md5(f"{group}:{msg.id}".encode()).hexdigest()[:8]
    filename = f"{h}_{msg.id}.{ext}"
    out_path = VIDEO_DIR / filename
    video_id = f"{group}:{msg.id}"

    try:
        await client.download_media(msg, str(out_path))
    except Exception as e:
        log.error(f"实时下载失败: {e}")
        return

    make_thumb(out_path)

    # 保留已有记录的手动设置字段
    existing = get_existing_entry(db, video_id)
    caption  = (msg.text or "").strip()

    entry = {
        "id":           video_id,
        "file":         f"videos/{filename}",
        "thumb":        make_thumb_url(f"videos/{filename}"),
        "title":        existing.get("title") if existing else (caption[:120] if caption else filename),
        "group":        group,
        "group_id":     group,
        "cat":          existing.get("cat") if existing and existing.get("cat") else NEW_VIDEO_CAT,
        "duration":     attr["duration"],
        "duration_str": format_dur(attr["duration"]),
        "size_mb":      round(size_mb, 2),
        "mime":         doc.mime_type,
        "views":        existing.get("views", 0) if existing else 0,
        "likes":        existing.get("likes", 0) if existing else 0,
        "tags":         existing.get("tags", []) if existing else [],
        "date":         msg.date.isoformat() if msg.date else datetime.utcnow().isoformat(),
        "synced_at":    datetime.utcnow().isoformat(),
    }

    existing_idx = next((i for i, v in enumerate(db["videos"]) if v.get("id") == video_id), None)
    if existing_idx is not None:
        db["videos"][existing_idx] = entry
    else:
        db["videos"].insert(0, entry)

    mark_downloaded(db, msg.id, group)
    db["stats"]["total"] = len(db["videos"])
    save_db(db)
    log.info(f"实时下载完成: {filename}，已归入分类：{NEW_VIDEO_CAT}")

# ── 入口 ──────────────────────────────────────────────────────────────────────
async def main():
    if not API_ID or not API_HASH or not PHONE:
        raise SystemExit("❌ 请在 .env 中填写 TG_API_ID, TG_API_HASH, TG_PHONE")
    if not WATCH_GROUPS or WATCH_GROUPS == ['']:
        raise SystemExit("❌ 请在 .env 中填写 TG_GROUPS")

    log.info(f"📁 新同步视频将归入分类：{NEW_VIDEO_CAT}")

    # 第一步：启动前扫描本地，确保数据库完整，保留手动分类
    db = rebuild_db()
    generate_thumbs()

    # 第二步：连接 Telegram 并预热所有 DC
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start(phone=PHONE)
    log.info("✅ Telegram 客户端已连接")

    log.info("正在授权所有数据中心...")
    for dc_id in [1, 2, 3, 4, 5]:
        try:
            sender = await client._borrow_exported_sender(dc_id)
            await client._return_exported_sender(sender)
            log.info(f"DC{dc_id} ✅")
        except Exception as e:
            log.warning(f"DC{dc_id} 跳过: {e}")

    # 第三步：批量拉取各群组历史视频
    for group in WATCH_GROUPS:
        g = group.strip()
        if g:
            await sync_group(client, g, db)

    # 第四步：同步完成后重建数据库、生成缩略图、去重
    log.info("📦 同步完成，重新扫描本地目录确保数据完整...")
    rebuild_db()
    generate_thumbs()
    dedup_videos()

    # 第五步：进入实时监听
    register_realtime(client, db)
    log.info("👂 实时监听模式已启动，等待新消息…")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
