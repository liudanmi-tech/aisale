"""端到端：走完 9 步核心链路，并覆盖撤销、计划失效、驳回重做、上游未通过拦截。"""
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_flow.db")
os.environ["STEP_DELAY"] = "0"
os.environ["LLM_ENABLED"] = "false"
if os.path.exists("test_flow.db"):
    os.remove("test_flow.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

P = "/api/v1/projects/p1"


def wait_until(client, cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timeout")


def nodes(c, t=None):
    return [n for n in c.get(P + "/canvas").json()["nodes"] if t is None or n["type"] == t]


def chat(c, text, selection=None):
    r = c.post(P + "/agent/chat", json={"text": text, "selection": selection or []})
    assert r.status_code == 200, r.text
    return c.get(P + "/canvas").json()["pending_patch"]


def approve_all(c):
    for r in c.get("/api/v1/reviews", params={"status": "wait"}).json():
        assert c.post(f"/api/v1/reviews/{r['id']}/decide", json={"decision": "pass"}).status_code == 200


def flow(c):
    return [s["done"] for s in c.get(P + "/flow").json()]


def test_full_flow():
    with TestClient(app) as c:
        # 上游未通过时拦截：还没有视频就跑评测
        assert chat(c, "跑评测") is None
        assert "还没有视频" in c.get(P + "/chat").json()[-1]["text"]

        # 1 洗剧本 → 2 计划 + 预览 → 执行
        w = c.post(P + "/wash", json={"ref_ad_no": 13}).json()
        patch = chat(c, w["prompt"], [w["node_id"]])
        assert patch and patch["summary"] == "写剧本" and len([o for o in patch["ops"] if o["op"] == "create_node"]) == 3
        # 调整数量 3 → 4
        assert c.post(f"{P}/patches/{patch['id']}/adjust", json={"count": 4}).json()["ok"]
        patch = c.get(P + "/canvas").json()["pending_patch"]
        assert len([o for o in patch["ops"] if o["op"] == "create_node"]) == 4
        before = len(nodes(c, "script"))
        assert c.post(f"{P}/patches/{patch['id']}/apply").status_code == 200
        wait_until(c, lambda: all(n["status"] == "wait" for n in nodes(c, "script")[before:]))
        assert len(nodes(c, "script")) == before + 4

        # 撤销整组
        assert c.post(P + "/undo").json()["ok"]
        assert len(nodes(c, "script")) == before
        patch = chat(c, "给小商贩写 2 个续航剧本")
        c.post(f"{P}/patches/{patch['id']}/apply")
        wait_until(c, lambda: all(n["status"] == "wait" for n in nodes(c, "script")[before:]))

        # 计划生成后画布被修改 → 计划失效
        stale = chat(c, "给学生写 1 个拍照剧本")
        s1 = nodes(c, "script")[0]
        c.patch(f"{P}/nodes/{s1['id']}", json={"data": {"note": "manual edit"}})
        assert c.post(f"{P}/patches/{stale['id']}/apply").status_code == 409

        # 驳回 → 自动重做 → 回到待审核且版本 +1
        r = next(r for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["module"] == "剧本工厂")
        assert c.post(f"/api/v1/reviews/{r['id']}/decide", json={"decision": "reject", "comment": ""}).status_code == 400
        c.post(f"/api/v1/reviews/{r['id']}/decide", json={"decision": "reject", "comment": "换成停电场景"})
        wait_until(c, lambda: next(n for n in nodes(c) if n["id"] == r["node_id"])["status"] == "wait")
        assert next(n for n in nodes(c) if n["id"] == r["node_id"])["data"]["version"] == 2

        # 3 审核通过剧本 → 4 视频 → 5 审核视频
        approve_all(c)
        patch = chat(c, "生成视频")
        assert patch["summary"] == "生成视频"
        c.post(f"{P}/patches/{patch['id']}/apply")
        wait_until(c, lambda: nodes(c, "video") and all(n["status"] == "wait" for n in nodes(c, "video")))
        approve_all(c)

        # 6 评测 → 查询最高 CTR
        patch = chat(c, "跑评测")
        c.post(f"{P}/patches/{patch['id']}/apply")
        wait_until(c, lambda: nodes(c, "eval") and nodes(c, "eval")[0]["status"] == "wait")
        approve_all(c)
        c.post(P + "/agent/chat", json={"text": "哪个视频预测 CTR 最高？"})
        assert "预测 CTR 最高" in c.get(P + "/chat").json()[-1]["text"]

        # 7 投放方案 → 审核 → 下发
        patch = chat(c, "生成投放方案")
        c.post(f"{P}/patches/{patch['id']}/apply")
        wait_until(c, lambda: nodes(c, "deliver") and nodes(c, "deliver")[0]["status"] == "wait")
        d = nodes(c, "deliver")[0]
        assert c.post(f"/api/v1/nodes/{d['id']}/launch").status_code == 409  # 未审核不能下发
        approve_all(c)
        assert c.post(f"/api/v1/nodes/{d['id']}/launch").status_code == 200

        # 8 数据回收 + 优化建议
        wait_until(c, lambda: nodes(c, "opt") and nodes(c, "opt")[0]["status"] == "wait")
        m = c.get(P + "/metrics").json()
        assert not m["sample"] and m["ranking"] and m["kpis"]["impressions"] > 0
        assert nodes(c, "deliver")[0]["status"] == "live"

        # 9 采纳 → 迭代计划 → 执行
        approve_all(c)
        patch = c.get(P + "/canvas").json()["pending_patch"]
        assert patch["summary"] == "迭代再生成"
        assert c.post(f"{P}/patches/{patch['id']}/apply").status_code == 200
        assert flow(c) == [True] * 9

        # 整理画布 + 撤销整理
        c.post(P + "/agent/chat", json={"text": "整理画布"})
        c.post(P + "/undo")


def test_new_project_and_creatives():
    with TestClient(app) as c:
        r = c.post("/api/v1/projects", json={"name": "Infinix 学生拍照 · 巴基斯坦", "market": "巴基斯坦", "selling_point": "拍照"})
        pid = r.json()["id"]
        snap = c.get(f"/api/v1/projects/{pid}/canvas").json()
        assert [n["type"] for n in snap["nodes"]] == ["sp", "aud", "aud"]
        assert any(p["id"] == pid and p["thumb"] for p in c.get("/api/v1/projects").json())
        c.post(f"/api/v1/projects/{pid}/wash", json={"ref_ad_no": 14})
        res = c.post(f"/api/v1/projects/{pid}/agent/chat", json={"text": "给学生写 2 个拍照剧本"}).json()
        assert res is not None and c.get(f"/api/v1/projects/{pid}/canvas").json()["pending_patch"]["summary"] == "写剧本"
        assert c.post("/api/v1/projects", json={"name": " "}).status_code == 400
        assert isinstance(c.get("/api/v1/creatives", params={"status": "live"}).json(), list)


def test_scripts_without_ref_ad_picks_from_library():
    """新项目没选爆款，直接让 Agent 写剧本：自动从爆款库挑一条同卖点的放上画布。"""
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "phone", "market": "尼日利亚", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "给小商贩写 3 个续航剧本"})
        patch = c.get(P + "/canvas").json()["pending_patch"]
        assert patch and patch["summary"] == "写剧本" and "从爆款库选出" in patch["steps"][0]
        assert c.post(f"{P}/patches/{patch['id']}/apply").status_code == 200
        nodes = c.get(P + "/canvas").json()["nodes"]
        ads = [n for n in nodes if n["type"] == "ad"]
        assert len(ads) == 1 and ads[0]["status"] == "pass" and ads[0]["title"].startswith("爆款 #")
        assert sum(n["type"] == "script" for n in nodes) == 3
        assert c.get(P + "/flow").json()[0]["done"]


def test_pass_nodes_from_canvas():
    """画布上直接通过待审核节点（单个或批量）。"""
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "审核测试", "market": "尼日利亚", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "给小商贩写 2 个续航剧本"})
        c.post(f"{P}/patches/{c.get(P + '/canvas').json()['pending_patch']['id']}/apply")
        scripts = lambda: [n for n in c.get(P + "/canvas").json()["nodes"] if n["type"] == "script"]  # noqa: E731
        wait_until(c, lambda: all(n["status"] == "wait" for n in scripts()))
        ids = [n["id"] for n in scripts()]
        assert c.post("/api/v1/reviews/pass-nodes", json={"node_ids": ids[:1]}).json() == {"passed": 1}
        assert c.post("/api/v1/reviews/pass-nodes", json={"node_ids": ids}).json() == {"passed": 1}  # 已通过的不重复处理
        assert all(n["status"] == "pass" for n in scripts())
        assert "已通过审核" in c.get(P + "/chat").json()[-1]["text"]


def test_revise_and_reject_on_canvas():
    """选中剧本后对 Agent 说怎么改：在原节点上改稿并重新提交审核；画布上驳回要写理由。"""
    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "改稿测试", "market": "尼日利亚", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "给小商贩写 1 个续航剧本"})
        c.post(f"{P}/patches/{c.get(P + '/canvas').json()['pending_patch']['id']}/apply")
        script = lambda: next(n for n in c.get(P + "/canvas").json()["nodes"] if n["type"] == "script")  # noqa: E731
        wait_until(c, lambda: script()["status"] == "wait")
        nid, before = script()["id"], len(c.get(P + "/canvas").json()["nodes"])

        c.post(P + "/agent/chat", json={"text": "第 1 镜口播更口语一点", "selection": [nid]})
        assert "正在按" in c.get(P + "/chat").json()[-1]["text"]
        wait_until(c, lambda: script()["status"] == "wait")
        s = script()
        assert s["data"]["version"] == 2 and "已按意见修改" in s["data"]["shots"][0][3]
        assert len(c.get(P + "/canvas").json()["nodes"]) == before  # 原节点上改，不新增节点
        assert len([r for r in c.get("/api/v1/reviews", params={"status": "wait"}).json() if r["node_id"] == nid]) == 1

        assert c.post("/api/v1/reviews/reject-node", json={"node_id": nid, "comment": " "}).status_code == 400
        assert c.post("/api/v1/reviews/reject-node", json={"node_id": nid, "comment": "换成停电场景"}).json()["ok"]
        wait_until(c, lambda: script()["status"] == "wait" and script()["data"]["version"] == 3)
        assert c.post("/api/v1/reviews/reject-node", json={"node_id": "n_none", "comment": "x"}).status_code == 409

        c.post(P + "/agent/chat", json={"text": "第 2 镜换成雨天", "selection": []})  # 只有一个剧本时不选也能改
        assert "正在按" in c.get(P + "/chat").json()[-1]["text"] or "要改哪个剧本" in c.get(P + "/chat").json()[-1]["text"]


def test_migrate_layouts_once():
    """老项目（没有 layout_v）启动时整理一次，按展开后的尺寸排，不重叠；新项目不动。"""
    from app import canvas
    from app.db import SessionLocal
    from app.models import Project

    with TestClient(app) as c:
        pid = c.post("/api/v1/projects", json={"name": "老布局", "market": "尼日利亚", "selling_point": "续航"}).json()["id"]
        P = f"/api/v1/projects/{pid}"
        c.post(P + "/agent/chat", json={"text": "给小商贩写 2 个续航剧本"})
        c.post(f"{P}/patches/{c.get(P + '/canvas').json()['pending_patch']['id']}/apply")
        with SessionLocal() as db:
            p = db.get(Project, pid)
            p.flags = {k: v for k, v in (p.flags or {}).items() if k != "layout_v"}
            for k, n in enumerate(canvas.nodes_of(db, pid, "script")):  # 模拟老版本的小卡片间距
                n.x, n.y = 320, 100 + k * 124
            db.commit()
            assert canvas.migrate_layouts(db) == 1 and canvas.migrate_layouts(db) == 0
        s = sorted((n for n in c.get(P + "/canvas").json()["nodes"] if n["type"] == "script"), key=lambda n: n["y"])
        assert s[0]["x"] == canvas.COL_X[1] and s[1]["y"] - s[0]["y"] >= canvas.NODE_SIZE["script"][1]
