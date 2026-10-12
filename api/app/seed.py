"""演示数据：爆款库、卖点、人群包与一个预置项目。真实数据接入第三方情报后替换。"""
from sqlalchemy.orm import Session

from app import canvas
from app.models import Audience, ChatMessage, Project, RefAd, SellingPoint, new_id

SHOTS = {
    "续航": [
        ["0–3s", "停电夜，市场摊位一片漆黑，只有手机亮着", "Light don cut again? My phone still dey kampe!", "又停电了？我的手机还撑得住！"],
        ["3–7s", "摊主一边收款一边刷视频", "From morning till night, no charger.", "从早到晚，不用充电。"],
        ["7–11s", "产品特写：电池参数（官方素材）", "6000mAh big battery.", "6000mAh 大电池。"],
        ["11–15s", "顾客围过来问价，CTA 出现", "Get am for TECNO shop near you!", "附近 TECNO 门店就能买！"],
    ],
    "拍照": [
        ["0–3s", "两部手机同时拍夜景，左暗右亮", "Which one be better? Look am well!", "哪个更好？仔细看！"],
        ["3–7s", "朋友聚会夜拍合影", "Night photos wey clear like day.", "夜拍清楚得像白天。"],
        ["7–11s", "产品特写：镜头与参数（官方素材）", "AI night camera.", "AI 夜拍镜头。"],
        ["11–15s", "分享到社交平台，CTA", "Shop now!", "立即购买！"],
    ],
}
SHOTS["存储"] = SHOTS["拍照"]

ADS = [
    (12, "竞品 A", "尼日利亚", "夜拍对比实测", "对比实测", "拍照", 21, "1.8–2.4%", 34, False, 92),
    (13, "竞品 B", "尼日利亚", "停电一整天还有电", "痛点提问", "续航", 18, "1.5–2.0%", 29, True, 88),
    (14, "传音历史", "巴基斯坦", "婚礼现场自拍", "故事剧情", "拍照", 26, "2.0–2.6%", 38, False, 90),
    (15, "竞品 C", "巴基斯坦", "开箱 30 秒", "开箱", "性价比", 15, "1.2–1.6%", 25, True, 81),
    (16, "竞品 A", "尼日利亚", "市场摊主一天", "故事剧情", "续航", 30, "1.9–2.5%", 36, False, 91),
    (17, "竞品 D", "巴基斯坦", "256G 装下全部照片", "反差", "存储", 12, "1.1–1.5%", 22, True, 77),
    (18, "竞品 B", "尼日利亚", "学生党拍 vlog", "开箱", "拍照", 16, "1.6–2.1%", 31, True, 85),
    (19, "传音历史", "尼日利亚", "足球之夜直播不卡", "痛点提问", "性能", 20, "1.7–2.2%", 33, False, 87),
    (20, "竞品 C", "巴基斯坦", "斋月夜晚团聚", "故事剧情", "拍照", 24, "2.1–2.7%", 37, True, 89),
    (21, "竞品 D", "尼日利亚", "10 分钟充一半", "对比实测", "续航", 14, "1.4–1.8%", 27, True, 80),
]


MARKET_AUDIENCES = {
    "尼日利亚": [("小商贩", "尼日利亚 · 25–35 岁"), ("学生", "尼日利亚 · 18–24 岁")],
    "巴基斯坦": [("年轻家庭", "巴基斯坦 · 25–40 岁"), ("学生", "巴基斯坦 · 18–24 岁")],
}


def new_project(db: Session, name: str, market: str, brand: str = "TECNO", model_sku: str = "Camon", selling_point: str = "续航") -> Project:
    """新建投放项目：放好卖点与目标市场的人群包节点，Agent 从这里开始。"""
    p = Project(id=new_id("p"), name=name, brand=brand, model_sku=model_sku, market=market, counters={}, flags={})
    db.add(p)
    db.flush()
    sp = db.query(SellingPoint).filter(SellingPoint.title == selling_point).first()
    canvas.create_node(db, p, "sp", sub=sp.specs if sp else "", status="pass", data={"selling_point": selling_point},
                       x=40, y=40, title=f"卖点 · {selling_point}")
    for i, (aud, sub) in enumerate(MARKET_AUDIENCES.get(market, MARKET_AUDIENCES["尼日利亚"])):
        canvas.create_node(db, p, "aud", sub=sub, status="pass", data={"audience": aud}, x=40, y=164 + i * 124, title=f"人群包 · {aud}")
    db.add(ChatMessage(project_id=p.id, role="agent", content={
        "text": f"新项目「{name}」已创建。先去爆款库选一条参考爆款点「一键洗剧本」，或者直接告诉我要给哪个人群写什么卖点的剧本。"}))
    db.commit()
    return p


def seed(db: Session) -> None:
    if db.get(Project, "p1"):
        return
    for no, brand, market, title, hook, sp, days, ctr, vtr, est, score in ADS:
        db.add(RefAd(id=f"ad_{no}", no=no, source="第三方情报" if brand != "传音历史" else "传音历史投放", brand=brand,
                     market=market, title=title, hook=hook, selling_point=sp, days_running=days, variants=3 + no % 4,
                     ctr_range=ctr, vtr=vtr, is_estimated=est, hot_score=score,
                     dna={"hook": hook, "selling_point": sp, "sp_at": "第 3 秒", "persona": "本地年轻人", "bgm": "Afrobeats",
                          "cta": "门店", "shots": SHOTS.get(sp, SHOTS["拍照"]), "intent_ratio": 7.2}))
    db.add_all([
        SellingPoint(id="sp_1", model_sku="Camon", title="续航", specs="6000mAh · 18W 快充", compliant_copy="不承诺具体使用天数", priority="P0"),
        SellingPoint(id="sp_2", model_sku="Camon", title="拍照", specs="AI 夜拍 · 50MP", compliant_copy="样张需为实拍", priority="P0"),
        SellingPoint(id="sp_3", model_sku="Camon", title="存储", specs="256GB", compliant_copy="—", priority="P1"),
        Audience(id="aud_1", market="尼日利亚", name="小商贩", tags={"age": "25–35", "interest": ["小生意"], "pain": "续航"}),
        Audience(id="aud_2", market="尼日利亚", name="学生", tags={"age": "18–24", "interest": ["拍照", "社交"], "pain": "拍照"}),
        Audience(id="aud_3", market="巴基斯坦", name="年轻家庭", tags={"age": "25–40", "interest": ["婚礼", "斋月"]}),
    ])
    p = Project(id="p1", name="TECNO 新机 · 尼日利亚", market="尼日利亚", counters={"ad": 0}, flags={})
    db.add(p)
    db.flush()
    ad = canvas.create_node(db, p, "ad", sub="对比实测 · 尼日利亚", status="pass", data={"ref_ad_no": 12}, x=40, y=40, title="爆款 #12")
    sp = canvas.create_node(db, p, "sp", sub="6000mAh · 18W 快充", status="pass", data={"selling_point": "续航"}, x=40, y=164, title="卖点 · 续航")
    a1 = canvas.create_node(db, p, "aud", sub="尼日利亚 · 25–35 岁", status="pass", data={"audience": "小商贩"}, x=40, y=288, title="人群包 · 小商贩")
    a2 = canvas.create_node(db, p, "aud", sub="尼日利亚 · 18–24 岁", status="pass", data={"audience": "学生"}, x=40, y=412, title="人群包 · 学生")
    s1 = canvas.create_node(db, p, "script", sub="续航 · 小商贩 · 15s", status="pass", x=320, y=100,
                            data={"selling_point": "续航", "audience": "小商贩", "version": 1, "shots": SHOTS["续航"]})
    s2 = canvas.create_node(db, p, "script", sub="拍照 · 学生 · 15s", status="none", x=320, y=224,
                            data={"selling_point": "拍照", "audience": "学生", "version": 1, "shots": SHOTS["拍照"]})
    for src, dst in [(ad, s1), (a1, s1), (sp, s1), (ad, s2), (a2, s2)]:
        canvas.connect(db, p.id, src.id, dst.id)
    canvas.add_review(db, s2, "拍照卖点 · 学生，夜拍对比钩子，4 镜 15 秒，合规自检通过",
                      "参考 爆款 #12 的「对比实测」结构；与参考素材相似度 18%（阈值 40%）；禁用词 0 处")
    db.add(ChatMessage(project_id=p.id, role="agent", content={
        "text": f"你好，我是投放 Agent。你说要做什么，我会先给出执行计划和画布预览，你确认后才改动画布。\n当前：{{{{{s2.id}}}}} 待审核。"}))
    db.commit()
