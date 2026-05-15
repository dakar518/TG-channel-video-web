#!/usr/bin/env python3
"""
api_server.py — ReelVault 后端 API
支持：JWT 认证、Telegram MFA、视频管理、上传、删除、分类、标签
"""

import json, os, subprocess, shutil, random, time, hashlib
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt

# ── 配置 ─────────────────────────────────────────────────────────────────────
DB_FILE        = Path("videos.json")
VIDEO_DIR      = Path("videos")
THUMB_DIR      = Path("thumbs")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
JWT_SECRET     = os.getenv("JWT_SECRET", "reelvault_secret")
JWT_EXPIRE_H   = 24  # token 有效期（小时）
TG_PHONE       = os.getenv("TG_PHONE", "")
TG_API_ID      = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH    = os.getenv("TG_API_HASH", "")
SESSION_NAME   = os.getenv("TG_SESSION", "tg_session")

VIDEO_DIR.mkdir(exist_ok=True)
THUMB_DIR.mkdir(exist_ok=True)

app = FastAPI(title="ReelVault API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 静态文件 ──────────────────────────────────────────────────────────────────
app.mount("/videos", StaticFiles(directory=str(VIDEO_DIR)), name="videos")
app.mount("/thumbs",  StaticFiles(directory=str(THUMB_DIR)),  name="thumbs")

# ── JWT ───────────────────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)

def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "未登录，请先登录管理后台")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "登录已过期，请重新登录")
    except Exception:
        raise HTTPException(401, "无效的登录凭证")

# ── MFA 验证码存储（内存，重启失效） ─────────────────────────────────────────
mfa_codes: dict = {}  # {username: {code, expires}}

async def send_tg_code(code: str) -> bool:
    """通过 Telegram 给自己发验证码"""
    try:
        from telethon import TelegramClient
        client = TelegramClient(SESSION_NAME, TG_API_ID, TG_API_HASH)
        await client.connect()
        # 给自己发消息
        await client.send_message("me", f"🔐 ReelVault 管理后台验证码：{code}\n\n有效期 5 分钟，请勿泄露。")
        await client.disconnect()
        return True
    except Exception as e:
        print(f"Telegram 发送验证码失败: {e}")
        return False

# ── 数据库 ────────────────────────────────────────────────────────────────────
def read_db() -> dict:
    if not DB_FILE.exists():
        return {"videos": [], "synced_ids": [], "stats": {"total": 0, "today": 0, "groups": []}}
    try:
        content = DB_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return {"videos": [], "synced_ids": [], "stats": {"total": 0, "today": 0, "groups": []}}
        return json.loads(content)
    except Exception:
        return {"videos": [], "synced_ids": [], "stats": {"total": 0, "today": 0, "groups": []}}

def write_db(db: dict):
    tmp = DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DB_FILE)

def format_dur(sec) -> str:
    sec = int(float(sec or 0))
    s = sec % 60; m = (sec // 60) % 60; h = sec // 3600
    if h: return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except:
        return 0.0

def get_dimensions(path: Path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15
        )
        s = json.loads(r.stdout)["streams"][0]
        return s.get("width", 0), s.get("height", 0)
    except:
        return 0, 0

def make_thumb(video_path: Path) -> bool:
    thumb = THUMB_DIR / f"{video_path.stem}.jpg"
    if thumb.exists():
        return True
    try:
        subprocess.run(
            ["ffmpeg", "-i", str(video_path), "-ss", "00:00:01",
             "-vframes", "1", "-q:v", "2", str(thumb), "-y"],
            capture_output=True, timeout=30
        )
        return thumb.exists()
    except:
        return False

# ── 页面路由 ──────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/admin")
def admin():
    return FileResponse("admin.html")

# ── 认证接口 ──────────────────────────────────────────────────────────────────
class LoginStep1Body(BaseModel):
    username: str
    password: str

class LoginStep2Body(BaseModel):
    username: str
    code:     str

@app.post("/api/auth/login")
async def login_step1(body: LoginStep1Body):
    """第一步：验证账号密码，发送 Telegram 验证码"""
    if body.username != ADMIN_USERNAME:
        raise HTTPException(401, "账号或密码错误")
    # 密码验证（简单哈希比对）
    pwd_hash = hashlib.sha256(body.password.encode()).hexdigest()
    expected = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
    if pwd_hash != expected:
        raise HTTPException(401, "账号或密码错误")

    # 生成 6 位验证码
    code = str(random.randint(100000, 999999))
    mfa_codes[body.username] = {
        "code":    code,
        "expires": time.time() + 300,  # 5分钟有效
    }

    # 发送 Telegram 验证码
    sent = await send_tg_code(code)
    if not sent:
        # 发送失败时在控制台打印（开发调试用）
        print(f"[DEBUG] MFA 验证码: {code}")
        return {"success": True, "message": "验证码已发送（Telegram 连接失败，请查看服务器控制台）"}

    # 隐藏手机号中间部分
    phone_hint = TG_PHONE[:4] + "****" + TG_PHONE[-2:] if len(TG_PHONE) > 6 else "****"
    return {"success": True, "message": f"验证码已发送到您的 Telegram（{phone_hint}）"}

@app.post("/api/auth/verify")
async def login_step2(body: LoginStep2Body):
    """第二步：验证 Telegram 验证码，返回 JWT"""
    entry = mfa_codes.get(body.username)
    if not entry:
        raise HTTPException(401, "请先完成账号密码验证")
    if time.time() > entry["expires"]:
        del mfa_codes[body.username]
        raise HTTPException(401, "验证码已过期，请重新登录")
    if body.code.strip() != entry["code"]:
        raise HTTPException(401, "验证码错误")

    del mfa_codes[body.username]
    token = create_token(body.username)
    return {"success": True, "token": token, "expires_in": JWT_EXPIRE_H * 3600}

@app.post("/api/auth/logout")
def logout(user: str = Depends(verify_token)):
    return {"success": True}

@app.get("/api/auth/me")
def me(user: str = Depends(verify_token)):
    return {"username": user}

# ── 统计（公开）──────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    db = read_db()
    stats = db.get("stats", {})
    stats["total"] = len(db.get("videos", []))
    return stats

# ── 视频列表（公开）──────────────────────────────────────────────────────────
@app.get("/api/videos")
def list_videos(
    cat:   Optional[str] = None,
    tag:   Optional[str] = None,
    q:     Optional[str] = None,
    sort:  str = "newest",
    page:  int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=9999),
):
    db   = read_db()
    vids = db.get("videos", [])
    if cat: vids = [v for v in vids if v.get("cat") == cat]
    if tag: vids = [v for v in vids if tag in (v.get("tags") or [])]
    if q:
        q_lo = q.lower()
        vids = [v for v in vids if
                q_lo in v.get("title","").lower() or
                q_lo in " ".join(v.get("tags",[])).lower() or
                q_lo in v.get("group","").lower()]
    if sort == "popular":    vids.sort(key=lambda v: v.get("views",0),    reverse=True)
    elif sort == "liked":    vids.sort(key=lambda v: v.get("likes",0),    reverse=True)
    elif sort == "duration": vids.sort(key=lambda v: v.get("duration",0), reverse=True)
    elif sort == "size":     vids.sort(key=lambda v: v.get("size_mb",0),  reverse=True)
    else: vids.sort(key=lambda v: v.get("synced_at",""), reverse=True)
    total = len(vids)
    start = (page-1)*limit
    return {"total": total, "page": page, "pages": (total+limit-1)//limit, "data": vids[start:start+limit]}

# ── 分类标签（公开）──────────────────────────────────────────────────────────
@app.get("/api/categories")
def get_categories():
    db   = read_db()
    cats = set(); tags = set()
    for v in db.get("videos", []):
        if v.get("cat"): cats.add(v["cat"])
        for t in (v.get("tags") or []): tags.add(t)
    return {"categories": sorted(cats), "tags": sorted(tags)}

# ── 单个视频（公开）──────────────────────────────────────────────────────────
@app.get("/api/videos/{video_id:path}")
def get_video(video_id: str):
    db = read_db()
    for v in db.get("videos", []):
        if v.get("id") == video_id:
            return v
    raise HTTPException(404, "Video not found")

# ── 以下接口需要登录 ──────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_video(
    file:  UploadFile = File(...),
    title: str = Form(""),
    cat:   str = Form(""),
    tags:  str = Form(""),
    user:  str = Depends(verify_token),
):
    if not file.filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
        raise HTTPException(400, "仅支持 mp4/mov/avi/mkv 格式")
    safe_name = "upload_" + file.filename.replace(" ", "_")
    out_path  = VIDEO_DIR / safe_name
    with open(out_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    duration      = get_duration(out_path)
    width, height = get_dimensions(out_path)
    size_mb       = round(out_path.stat().st_size / 1024 / 1024, 2)
    make_thumb(out_path)
    now = datetime.utcnow().isoformat()
    entry = {
        "id":           f"upload:{out_path.stem}",
        "file":         f"videos/{safe_name}",
        "thumb":        f"/thumbs/{out_path.stem}.jpg",
        "title":        title or file.filename,
        "group":        "手动上传",
        "group_id":     "upload",
        "cat":          cat or "",
        "duration":     duration,
        "duration_str": format_dur(duration),
        "width":        width,
        "height":       height,
        "size_mb":      size_mb,
        "mime":         "video/mp4",
        "views":        0,
        "likes":        0,
        "tags":         [t.strip() for t in tags.split(",") if t.strip()],
        "date":         now,
        "synced_at":    now,
    }
    db = read_db()
    db["videos"].insert(0, entry)
    db["synced_ids"].append(entry["id"])
    db["stats"]["total"] = len(db["videos"])
    write_db(db)
    return {"success": True, "video": entry}

@app.delete("/api/videos/{video_id:path}")
def delete_video(video_id: str, user: str = Depends(verify_token)):
    db = read_db()
    target = next((v for v in db["videos"] if v.get("id") == video_id), None)
    if not target:
        raise HTTPException(404, "Video not found")
    f = Path(target["file"])
    if f.exists(): f.unlink()
    thumb = THUMB_DIR / f"{f.stem}.jpg"
    if thumb.exists(): thumb.unlink()
    db["videos"]     = [v for v in db["videos"] if v.get("id") != video_id]
    db["synced_ids"] = [i for i in db.get("synced_ids",[]) if i != video_id]
    db["stats"]["total"] = len(db["videos"])
    write_db(db)
    return {"success": True}

class BulkDeleteBody(BaseModel):
    ids: List[str]

@app.post("/api/videos/bulk-delete")
def bulk_delete(body: BulkDeleteBody, user: str = Depends(verify_token)):
    db = read_db()
    deleted = 0
    for video_id in body.ids:
        target = next((v for v in db["videos"] if v.get("id") == video_id), None)
        if target:
            f = Path(target["file"])
            if f.exists(): f.unlink()
            thumb = THUMB_DIR / f"{f.stem}.jpg"
            if thumb.exists(): thumb.unlink()
            deleted += 1
    db["videos"]     = [v for v in db["videos"] if v.get("id") not in body.ids]
    db["synced_ids"] = [i for i in db.get("synced_ids",[]) if i not in body.ids]
    db["stats"]["total"] = len(db["videos"])
    write_db(db)
    return {"success": True, "deleted": deleted}

class UpdateBody(BaseModel):
    title: Optional[str] = None
    cat:   Optional[str] = None
    tags:  Optional[List[str]] = None

@app.patch("/api/videos/{video_id:path}")
def update_video(video_id: str, body: UpdateBody, user: str = Depends(verify_token)):
    db = read_db()
    for v in db["videos"]:
        if v.get("id") == video_id:
            if body.title is not None: v["title"] = body.title
            if body.cat   is not None: v["cat"]   = body.cat
            if body.tags  is not None: v["tags"]  = body.tags
            write_db(db)
            return {"success": True, "video": v}
    raise HTTPException(404, "Video not found")

@app.post("/api/videos/{video_id:path}/like")
def like_video(video_id: str):
    db = read_db()
    for v in db["videos"]:
        if v.get("id") == video_id:
            v["likes"] = v.get("likes", 0) + 1
            write_db(db)
            return {"likes": v["likes"]}
    raise HTTPException(404, "Video not found")

@app.post("/api/videos/{video_id:path}/view")
def view_video(video_id: str):
    db = read_db()
    for v in db["videos"]:
        if v.get("id") == video_id:
            v["views"] = v.get("views", 0) + 1
            write_db(db)
            return {"views": v["views"]}
    raise HTTPException(404, "Video not found")
