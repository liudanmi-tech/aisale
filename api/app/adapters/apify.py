"""Apify 适配器：调用现成的 TikTok 抓取 Actor，拉监控账号的公开视频与指标。

启动：POST https://api.apify.com/v2/acts/{actor}/runs   （头 Authorization: Bearer <token>）
轮询：GET  /v2/actor-runs/{runId}，状态 SUCCEEDED 后读 GET /v2/datasets/{defaultDatasetId}/items
默认 Actor clockworks~tiktok-scraper，可在设置里换；不同 Actor 字段名略有差异，normalize() 做了兼容。
"""
import asyncio
from datetime import datetime, timezone

import httpx

from app import settings_store

BASE = "https://api.apify.com/v2"
transport: httpx.AsyncBaseTransport | None = None  # 测试时注入
POLL_SECONDS = 5.0


def _headers(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or settings_store.get_secret('apify')}"}


async def check_key(token: str) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.get(f"{BASE}/users/me", headers=_headers(token))
    if r.status_code in (401, 403):
        return False, "Token 无效或无权限"
    r.raise_for_status()
    name = (r.json().get("data") or {}).get("username") or ""
    return True, f"连接成功{'，账号 ' + name if name else ''}"


NO_DOWNLOADS = {"shouldDownloadVideos": False, "shouldDownloadCovers": False, "shouldDownloadSubtitles": False}


async def fetch_profiles(handles: list[str], per_profile: int = 30, timeout_seconds: float = 900) -> list[dict]:
    """拉一批账号最新的视频，返回 normalize 后的列表。"""
    return await _run({"profiles": handles, "resultsPerPage": per_profile, "profileSorting": "latest", **NO_DOWNLOADS}, timeout_seconds)


async def search_videos(queries: list[str], per_query: int = 30, timeout_seconds: float = 900) -> list[dict]:
    """按关键词搜视频（如 "Samsung Nigeria"），用来从视频作者里找账号。"""
    return await _run({"searchQueries": queries, "resultsPerPage": per_query, **NO_DOWNLOADS}, timeout_seconds)


async def _run(body: dict, timeout_seconds: float) -> list[dict]:
    actor = settings_store.get_models()["tiktok_actor"]
    async with httpx.AsyncClient(timeout=60, transport=transport) as c:
        r = await c.post(f"{BASE}/acts/{actor}/runs", headers=_headers(), json=body)
        r.raise_for_status()
        run = r.json()["data"]
        waited = 0.0
        while run.get("status") in ("READY", "RUNNING"):
            if waited >= timeout_seconds:
                raise TimeoutError("Apify 运行超时")
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            r = await c.get(f"{BASE}/actor-runs/{run['id']}", headers=_headers())
            r.raise_for_status()
            run = r.json()["data"]
        if run.get("status") != "SUCCEEDED":
            raise RuntimeError(f"Apify 运行失败：{run.get('status')}")
        r = await c.get(f"{BASE}/datasets/{run['defaultDatasetId']}/items", headers=_headers(), params={"clean": "true"})
        r.raise_for_status()
        items = r.json()
    return [v for v in (normalize(i) for i in items) if v]


def _num(*vals) -> int:
    for v in vals:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 0


def normalize(i: dict) -> dict | None:
    vid = str(i.get("id") or i.get("videoId") or i.get("aweme_id") or "")
    if not vid or i.get("error"):
        return None
    author = i.get("authorMeta") or i.get("author") or {}
    handle = (author.get("name") or author.get("uniqueId") or author.get("username") or "").lstrip("@")
    stats = i.get("stats") or i.get("statistics") or {}
    vm = i.get("videoMeta") or i.get("video") or {}
    ts = i.get("createTimeISO") or i.get("createTime")
    posted = None
    if isinstance(ts, (int, float)):
        posted = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    elif isinstance(ts, str) and ts:
        try:
            posted = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            posted = None
    covers = i.get("covers")
    tags = [t.get("name") if isinstance(t, dict) else str(t) for t in (i.get("hashtags") or [])]
    return {
        "external_id": vid, "handle": handle,
        "nickname": author.get("nickName") or author.get("nickname") or "",
        "followers": _num(author.get("fans"), author.get("followerCount"), author.get("followers")) or None,
        "verified": bool(author.get("verified")),
        "bio": author.get("signature") or author.get("bio") or "",
        "url": i.get("webVideoUrl") or i.get("url") or (f"https://www.tiktok.com/@{handle}/video/{vid}" if handle else ""),
        "cover": vm.get("coverUrl") or vm.get("cover") or (covers.get("default", "") if isinstance(covers, dict) else ""),
        "text": i.get("text") or i.get("desc") or "",
        "hashtags": [t for t in tags if t],
        "music": (i.get("musicMeta") or {}).get("musicName") or "",
        "duration": vm.get("duration"),
        "is_ad": bool(i.get("isAd") or i.get("isSponsored") or i.get("isPaidPartnership")),
        "posted_at": posted,
        "plays": _num(i.get("playCount"), stats.get("playCount"), i.get("views")),
        "likes": _num(i.get("diggCount"), stats.get("diggCount"), i.get("likes")),
        "comments": _num(i.get("commentCount"), stats.get("commentCount"), i.get("comments")),
        "shares": _num(i.get("shareCount"), stats.get("shareCount"), i.get("shares")),
        "collects": _num(i.get("collectCount"), stats.get("collectCount")),
        "raw": i,
    }
