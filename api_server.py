#!/usr/bin/env python3
"""
api_server.py — 简易 FastAPI 后端
把 videos.json 暴露为 REST API 供前端调用

安装: pip install fastapi uvicorn aiofiles
运行: uvicorn api_server:app --reload --port 8000
"""

import json
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DB_FILE   = Path("videos.json")
VIDEO_DIR = Path("videos")
THUMB_DIR = Path("thumbs")
FRONT_DIR = Path(".")   # index.html 所在目录

app = FastAPI(title="ReelVault API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

def read_db():
    if not DB_FILE.exists():
        return {"videos": [], "stats": {"total": 0, "today": 0, "groups": []}}
    return json.loads(DB_FILE.read_text(encoding="utf-8"))

# ── 静态文件 ──────────────────────────────────────────────────────────────────
if VIDEO_DIR.exists():
    app.mount("/videos", StaticFiles(directory=str(VIDEO_DIR)), name="videos")
if THUMB_DIR.exists():
    app.mount("/thumbs", StaticFiles(directory=str(THUMB_DIR)), name="thumbs")

# ── API 路由 ──────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/api/stats")
def get_stats():
    db = read_db()
    return db.get("stats", {})

@app.get("/api/videos")
def list_videos(
    cat:    Optional[str] = None,
    q:      Optional[str] = None,
    sort:   str = "newest",
    page:   int = Query(1, ge=1),
    limit:  int = Query(24, ge=1, le=9999),
):
    db    = read_db()
    vids  = db.get("videos", [])

    # 过滤
    if cat:
        vids = [v for v in vids if v.get("cat") == cat]
    if q:
        q_lo = q.lower()
        vids = [v for v in vids if q_lo in v.get("title","").lower()
                or q_lo in " ".join(v.get("tags",[])).lower()
                or q_lo in v.get("group","").lower()]

    # 排序
    if sort == "popular":
        vids.sort(key=lambda v: v.get("views", 0), reverse=True)
    elif sort == "liked":
        vids.sort(key=lambda v: v.get("likes", 0), reverse=True)
    elif sort == "duration":
        vids.sort(key=lambda v: v.get("duration", 0), reverse=True)
    else:  # newest
        vids.sort(key=lambda v: v.get("synced_at",""), reverse=True)

    total = len(vids)
    start = (page - 1) * limit
    return {
        "total": total,
        "page":  page,
        "pages": (total + limit - 1) // limit,
        "data":  vids[start:start+limit],
    }

@app.get("/api/videos/{video_id:path}")
def get_video(video_id: str):
    db = read_db()
    for v in db.get("videos", []):
        if v.get("id") == video_id:
            return v
    raise HTTPException(404, "Video not found")

@app.post("/api/videos/{video_id:path}/like")
def like_video(video_id: str):
    db = read_db()
    for v in db["videos"]:
        if v.get("id") == video_id:
            v["likes"] = v.get("likes", 0) + 1
            Path("videos.json").write_text(json.dumps(db, ensure_ascii=False, indent=2))
            return {"likes": v["likes"]}
    raise HTTPException(404, "Video not found")

@app.post("/api/videos/{video_id:path}/view")
def view_video(video_id: str):
    db = read_db()
    for v in db["videos"]:
        if v.get("id") == video_id:
            v["views"] = v.get("views", 0) + 1
            Path("videos.json").write_text(json.dumps(db, ensure_ascii=False, indent=2))
            return {"views": v["views"]}
    raise HTTPException(404, "Video not found")
