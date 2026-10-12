"""TikTok Marketing API 适配器。

真实模式按 TikTok Business API v1.3 的广告系列 / 广告组 / 广告三层结构下发，
字段需在拿到开发者应用后对照官方文档逐项核对。
"""
import asyncio
import uuid

import httpx

from app import config


async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{config.TIKTOK_BASE_URL}{path}", headers={"Access-Token": config.TIKTOK_ACCESS_TOKEN}, json=body)
        r.raise_for_status()
        d = r.json()
        if d.get("code") not in (0, None):
            raise RuntimeError(f"TikTok API {path}: {d.get('code')} {d.get('message')}")
        return d.get("data") or {}


async def create_campaign(name: str, daily_budget: float) -> str:
    if config.TIKTOK_MODE != "real":
        await asyncio.sleep(config.STEP_DELAY / 3)
        return f"cmp_{uuid.uuid4().hex[:8]}"
    d = await _post("/campaign/create/", {"advertiser_id": config.TIKTOK_ADVERTISER_ID, "campaign_name": name,
                                          "objective_type": "TRAFFIC", "budget_mode": "BUDGET_MODE_INFINITE"})
    return str(d["campaign_id"])


async def create_adgroup(campaign_id: str, name: str, targeting: dict, daily_budget: float) -> str:
    if config.TIKTOK_MODE != "real":
        await asyncio.sleep(config.STEP_DELAY / 3)
        return f"adg_{uuid.uuid4().hex[:8]}"
    d = await _post("/adgroup/create/", {"advertiser_id": config.TIKTOK_ADVERTISER_ID, "campaign_id": campaign_id,
                                         "adgroup_name": name, "budget_mode": "BUDGET_MODE_DAY", "budget": daily_budget,
                                         **targeting})
    return str(d["adgroup_id"])


async def create_ad(adgroup_id: str, name: str, video_url: str) -> str:
    if config.TIKTOK_MODE != "real":
        await asyncio.sleep(config.STEP_DELAY / 3)
        return f"ad_{uuid.uuid4().hex[:8]}"
    d = await _post("/ad/create/", {"advertiser_id": config.TIKTOK_ADVERTISER_ID, "adgroup_id": adgroup_id,
                                    "creatives": [{"ad_name": name, "video_url": video_url}]})
    return str((d.get("ad_ids") or [""])[0])
