"""生成传音机型库清单 app/data/transsion_catalog.json。有新机型发布时重新跑一遍。

步骤：
1. GSMArena 抓 TECNO / Infinix / itel 从 SINCE 年起发布的手机，以及每款的官方渲染图地址（礼貌限速）；
2. 下载渲染图，用多模态模型（OpenRouter，task=qc）框出图里每台手机：视角、颜色、是否被遮挡；
3. 每款取一个配色：未被遮挡的背面 + 正面 + 侧面 / 45°（有就要），写进清单（只存图片地址和框，不存图片）。

用法（在 api 目录）：
    LLM_ENABLED=true .venv/bin/python scripts/build_transsion_catalog.py --since 2024
可以分步：--crawl-only 只抓列表；--skip-crawl 用已有的 work/gsm.json 继续。
"""
import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
BRANDS = {"TECNO": ("tecno", 120), "Infinix": ("infinix", 119), "itel": ("itel", 131)}
SKIP = re.compile(r"pad|tab|watch|buds|book|laptop|\bit\d{3,}|\bace\b|magic|value|\bpower \d{3}\b", re.I)  # 平板、手表、功能机
BOX_PROMPT = """This is an official product render of the smartphone "{name}" on a white background. It may show several phones (different colours, front, back, side).
Return EVERY phone as JSON: {{"phones": [{{"box": [ymin, xmin, ymax, xmax], "view": "front|back|side|angle", "color": "colour name in English", "occluded": true/false}}]}}
- box: tight box of that one phone, coordinates normalized 0-1000.
- view: front = screen facing camera; back = back panel facing camera; side = pure side profile (thin edge); angle = three-quarter / tilted view.
- occluded: true if another phone overlaps/covers part of it.
Only output JSON."""


def crawl(since: int, out: Path) -> list[dict]:
    c = httpx.Client(headers=UA, timeout=30, follow_redirects=True)

    def get(url):
        for k in range(5):
            try:
                r = c.get(url)
            except httpx.HTTPError as e:  # 网络超时：等一下重试
                print("重试", url, e, flush=True)
                time.sleep(10 * (k + 1))
                continue
            if r.status_code == 429:
                time.sleep(20 * (k + 1))
                continue
            time.sleep(1.5)
            return r.text
        raise SystemExit(f"GSMArena 访问失败：{url}")

    models = json.loads(out.read_text()) if out.exists() else []  # 续跑：已抓过的机型页跳过
    done = {m["page"] for m in models}
    for brand, (slug, bid) in BRANDS.items():
        links, page = [], 1
        while page <= 6:
            url = f"https://www.gsmarena.com/{slug}-phones-{bid}.php" if page == 1 else f"https://www.gsmarena.com/{slug}-phones-f-{bid}-0-p{page}.php"
            got = [h for h, _ in re.findall(r'href="(' + slug + r'_[a-z0-9_]+-(\d+)\.php)"', get(url)) if "review" not in h]
            new = [h for h in dict.fromkeys(got) if h not in links]
            if not new:
                break
            links += new
            page += 1
        old = 0
        for href in links:
            if "https://www.gsmarena.com/" + href in done:
                old = 0
                continue
            html = get("https://www.gsmarena.com/" + href)
            year = (re.search(r'data-spec="year">([^<]+)', html) or [None, ""])[1].strip()
            name = (re.search(r'data-spec="modelname">([^<]+)', html) or [None, href])[1].strip()
            y = re.search(r"(20\d\d)", year)
            if not y or int(y.group(1)) < since:
                old += 1
                if old >= 6:  # 列表按新到旧，连续 6 款旧机型就停
                    break
                continue
            old = 0
            if SKIP.search(name):
                continue
            pid = href.rsplit("-", 1)[1].split(".")[0]
            pics = sorted(set(re.findall(r'https://fdn2?\.gsmarena\.com/vv/pics/[^"\']+\.(?:jpg|png)', get(f"https://www.gsmarena.com/{href.replace('-' + pid, '-pictures-' + pid)}"))))
            models.append({"brand": brand, "name": name, "announced": year, "page": "https://www.gsmarena.com/" + href, "pictures": pics})
            print(brand, name, year, len(pics), flush=True)
            out.write_text(json.dumps(models, ensure_ascii=False, indent=1))
    return models


def own_pictures(name: str, pics: list[str]) -> list[str]:
    """GSMArena 图片页偶尔混进相关机型的图：文件名要包含型号的全部关键词（4G/5G 后缀除外）。"""
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()[1:] if w not in ("4g", "5g")]
    key = "".join(words)
    keep = [p for p in pics if key and key in re.sub(r"[^a-z0-9]", "", p.rsplit("/", 1)[1].lower().rsplit(".", 1)[0])]
    return keep or pics[:0]


async def detect(models: list[dict], img_dir: Path, boxes_path: Path) -> dict:
    from app.adapters import llm
    import cv2
    boxes = json.loads(boxes_path.read_text()) if boxes_path.exists() else {}
    img_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(headers=UA, timeout=60, follow_redirects=True) as c:
        async def one(m, u):
            f = img_dir / u.rsplit("/", 1)[1]
            if not f.exists():
                async with sem:
                    r = await c.get(u)
                    r.raise_for_status()
                    f.write_bytes(r.content)
            if u in boxes:
                return
            ok, buf = cv2.imencode(".jpg", cv2.imread(str(f)), [cv2.IMWRITE_JPEG_QUALITY, 92])
            url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
            async with sem:
                for _ in range(3):
                    try:
                        msg = await llm.chat([{"role": "user", "content": [{"type": "text", "text": BOX_PROMPT.format(name=m["name"])},
                                                                           {"type": "image_url", "image_url": {"url": url}}]}],
                                             json_mode=True, task="qc", timeout=90)
                        boxes[u] = llm.parse_json(msg.get("content") or "").get("phones") or []
                        return
                    except Exception as e:  # noqa: BLE001
                        print("框选失败，重试", u, e, flush=True)
        await asyncio.gather(*(one(m, u) for m in models for u in own_pictures(m["name"], m["pictures"])))
    boxes_path.write_text(json.dumps(boxes, indent=1))
    return boxes


def _cover(b: list[int], others: list[list[int]]) -> float:
    """b 被其他框盖住的面积占比（粗算：各重叠矩形面积相加）。"""
    area = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    tot = 0
    for o in others:
        h, w = min(b[2], o[2]) - max(b[0], o[0]), min(b[3], o[3]) - max(b[1], o[1])
        if h > 0 and w > 0:
            tot += h * w
    return tot / area


def select(models: list[dict], boxes: dict) -> list[dict]:
    """每款取一个配色：背面（优先完全没遮挡；其次 45°；再其次只被轻微遮挡、把盖住的部分涂白）+ 正面 + 侧面 / 45°。"""
    out = []
    for m in models:
        if SKIP.search(m["name"]):
            continue
        phones = []
        for u in own_pictures(m["name"], m["pictures"]):
            ps = [p for p in boxes.get(u) or [] if isinstance(p.get("box") or p.get("box_2d"), list) and len(p.get("box") or p.get("box_2d")) == 4]
            bs = [[int(v) for v in (p.get("box") or p.get("box_2d"))] for p in ps]
            for k, (p, b) in enumerate(zip(ps, bs)):
                y0, x0, y1, x1 = b
                if p.get("view") not in ("front", "back", "side", "angle") or (y1 - y0) <= 80 or (x1 - x0) <= 40:
                    continue
                others = [o for j, o in enumerate(bs) if j != k]
                phones.append({"src": u, "box": b, "view": p["view"], "color": (p.get("color") or "").strip().lower(),
                               "occluded": bool(p.get("occluded")), "cover": _cover(b, others), "mask": others if p.get("occluded") else []})
        clean = [p for p in phones if not p["occluded"]]
        main_ = ([p for p in clean if p["view"] == "back"] + [p for p in clean if p["view"] == "angle"]
                 + sorted([p for p in phones if p["view"] == "back" and p["occluded"] and p["cover"] < 0.15], key=lambda p: p["cover"]))
        if not main_:
            continue
        color = main_[0]["color"]
        # 每个位置给几张候选（同配色优先），核验时挑第一张「只有一台手机」的
        pick = [{"slot": "main", "cands": main_[:4]}]
        for view in ("front", "angle", "side"):
            same = [p for p in clean if p["view"] == view and p["color"] == color] + [p for p in clean if p["view"] == view and p["color"] != color]
            if same:
                pick.append({"slot": view, "cands": same[:3]})
        brand = m["brand"]
        model = re.sub(rf"^{brand}\s+", "", m["name"], flags=re.I)
        year = int(re.search(r"(20\d\d)", m["announced"]).group(1))
        imgs = [{"slot": x["slot"], "cands": [{"src": p["src"], "box": p["box"], "view": p["view"], **({"mask": p["mask"]} if p["mask"] else {})}
                                             for p in x["cands"]]} for x in pick]
        out.append({"id": re.sub(r"[^a-z0-9]+", "-", f"{brand} {model}".lower()).strip("-"), "brand": brand, "name": f"{brand} {model}",
                    "model_sku": model, "series": model.split()[0], "announced": m["announced"], "year": year,
                    "color": color, "source": m["page"], "images": imgs})
    return out


VERIFY_PROMPT = """List every separate physical phone device visible in this product image (one entry per device; a device counts even if partly hidden behind another).
Output only JSON {"devices": [{"shows": "screen / back / edge", "where": "left / right / center / behind / front"}], "view": "front / back / side / angle / detail (close-up of the camera module)"}"""
VERIFY_MODEL = "google/gemini-2.5-pro"  # flash 常把叠在一起的两台数成一台


async def verify(cat: list[dict], img_dir: Path, cache_path: Path) -> list[dict]:
    """逐张核验候选裁剪：只有一台手机才要，并用模型重新判定视角（特写标成 detail）。"""
    from app.adapters import llm
    from app.catalog import _crop
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    sem = asyncio.Semaphore(6)

    async def check(c):
        key = f"{c['src']}|{c['box']}|{c.get('mask')}"
        if key not in cache and not os.getenv("SKIP_VERIFY_CALLS"):
            raw = _crop((img_dir / c["src"].rsplit("/", 1)[1]).read_bytes(), c["box"], c.get("mask"))
            url = "data:image/png;base64," + base64.b64encode(raw).decode()
            async with sem:
                for _ in range(3):
                    try:
                        msg = await llm.chat([{"role": "user", "content": [{"type": "text", "text": VERIFY_PROMPT}, {"type": "image_url", "image_url": {"url": url}}]}],
                                             json_mode=True, task="qc", timeout=120, model=VERIFY_MODEL)
                        cache[key] = llm.parse_json(msg.get("content") or "")
                        break
                    except Exception as e:  # noqa: BLE001
                        print("核验失败，重试", e, flush=True)
        return cache.get(key) or {}

    if not os.getenv("SKIP_VERIFY_CALLS"):
        await asyncio.gather(*(check(c) for m in cat for x in m["images"] for c in x["cands"]))
    cache_path.write_text(json.dumps(cache, indent=1))
    out = []
    for m in cat:
        imgs, seen = [], set()
        unverified = not all(f"{c['src']}|{c['box']}|{c.get('mask')}" in cache for x in m["images"] for c in x["cands"][:1])
        if unverified:  # 没核验到（比如模型额度用完）：取每个位置的第一张候选，导入时商品检查还会再查一遍
            imgs = [{**x["cands"][0]} for x in m["images"]]
            imgs = [i for k, i in enumerate(imgs) if i["view"] not in {j["view"] for j in imgs[:k]}]
            out.append({**m, "images": imgs, "unverified": True})
            continue
        for x in m["images"]:
            for c in x["cands"]:
                r = await check(c)
                n = len(r.get("devices") or []) if "devices" in r else r.get("phones")
                if str(n).isdigit() and int(n) == 1:
                    view = r.get("view") if r.get("view") in ("front", "back", "side", "angle", "detail") else c["view"]
                    if view in seen:
                        continue
                    seen.add(view)
                    imgs.append({k: v for k, v in {**c, "view": view}.items()})
                    break
        if imgs and any(i["view"] in ("back", "angle", "detail") for i in imgs):
            out.append({**m, "images": imgs})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--work", default="work/catalog")
    ap.add_argument("--crawl-only", action="store_true")
    ap.add_argument("--skip-crawl", action="store_true")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    gsm = work / "gsm.json"
    models = json.loads(gsm.read_text()) if a.skip_crawl else crawl(a.since, gsm)
    if a.crawl_only:
        return
    boxes = asyncio.run(detect(models, work / "img", work / "boxes.json"))
    cat = asyncio.run(verify(select(models, boxes), work / "img", work / "verify3.json"))
    dst = Path(__file__).resolve().parents[1] / "app" / "data" / "transsion_catalog.json"
    dst.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
    print(f"{len(cat)} 款机型 → {dst}")


if __name__ == "__main__":
    main()
