import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Project(Base):
    __tablename__ = "project"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String, default="TECNO")
    model_sku: Mapped[str] = mapped_column(String, default="Camon")
    market: Mapped[str] = mapped_column(String, default="尼日利亚")
    objective: Mapped[str] = mapped_column(String, default="ctr")
    version: Mapped[int] = mapped_column(Integer, default=1)
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    flags: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Node(Base):
    __tablename__ = "node"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    type: Mapped[str] = mapped_column(String)  # ad sp aud script video eval deliver data opt
    no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    sub: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="none")  # none run wait pass reject live failed
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Edge(Base):
    __tablename__ = "edge"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), index=True)
    source: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)


class RefAd(Base):
    __tablename__ = "ref_ad"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    no: Mapped[int] = mapped_column(Integer, unique=True)
    source: Mapped[str] = mapped_column(String)
    platform: Mapped[str] = mapped_column(String, default="TikTok")
    brand: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    hook: Mapped[str] = mapped_column(String)
    selling_point: Mapped[str] = mapped_column(String)
    days_running: Mapped[int] = mapped_column(Integer)
    variants: Mapped[int] = mapped_column(Integer, default=1)
    ctr_range: Mapped[str] = mapped_column(String)
    vtr: Mapped[float] = mapped_column(Float)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    hot_score: Mapped[int] = mapped_column(Integer)
    dna: Mapped[dict] = mapped_column(JSON, default=dict)


class SellingPoint(Base):
    __tablename__ = "selling_point"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    model_sku: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    specs: Mapped[str] = mapped_column(String)
    compliant_copy: Mapped[str] = mapped_column(String)
    priority: Mapped[str] = mapped_column(String)


class Audience(Base):
    __tablename__ = "audience"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewTask(Base):
    __tablename__ = "review_task"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    module: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    conclusion: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="wait")  # wait pass reject
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # user agent plan system
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Patch(Base):
    """Agent 产出的画布操作补丁：先预览，确认后应用，可整体撤销。"""

    __tablename__ = "patch"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    base_version: Mapped[int] = mapped_column(Integer)
    intent: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(String)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    cost: Mapped[str] = mapped_column(String, default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    ops: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="proposed")  # proposed applied cancelled superseded undone
    undo: Mapped[dict] = mapped_column(JSON, default=dict)
    chat_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MetricDaily(Base):
    __tablename__ = "metric_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    creative_node_id: Mapped[str] = mapped_column(String)
    day: Mapped[str] = mapped_column(String)
    spend: Mapped[float] = mapped_column(Float)
    impressions: Mapped[int] = mapped_column(Integer)
    clicks: Mapped[int] = mapped_column(Integer)
    completes: Mapped[int] = mapped_column(Integer)
    conversions: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)  # user / agent / system
    action: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Secret(Base):
    """第三方服务密钥：加密存储，接口只返回末 4 位。"""

    __tablename__ = "secret"
    name: Mapped[str] = mapped_column(String, primary_key=True)  # fal | openrouter
    ciphertext: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class WatchAccount(Base):
    """监控的 TikTok 账号：竞品官方号、本地达人、传音自家号（对照）。"""

    __tablename__ = "watch_account"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, default="TikTok")
    handle: Mapped[str] = mapped_column(String, index=True)  # 不带 @
    brand: Mapped[str] = mapped_column(String, default="")
    market: Mapped[str] = mapped_column(String, default="尼日利亚")
    kind: Mapped[str] = mapped_column(String, default="竞品官方")  # 竞品官方 / 达人 / 传音自有
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    nickname: Mapped[str] = mapped_column(String, default="")
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="new")  # new syncing ok error
    error: Mapped[str] = mapped_column(String, default="")
    last_synced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SourceVideo(Base):
    """从监控账号拉到的视频，保存最新指标；历史指标在 video_snapshot。"""

    __tablename__ = "source_video"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, default="TikTok")
    external_id: Mapped[str] = mapped_column(String, unique=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("watch_account.id"), index=True)
    url: Mapped[str] = mapped_column(String, default="")
    cover: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    music: Mapped[str] = mapped_column(String, default="")
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False)  # 平台标注的广告 / 付费合作
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plays: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    collects: Mapped[int] = mapped_column(Integer, default=0)
    ref_ad_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 已加入爆款库
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class VideoSnapshot(Base):
    __tablename__ = "video_snapshot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("source_video.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    plays: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)


class VideoAnalysis(Base):
    """单条视频的 AI 拆解（手机、卖点、场景、剧本类型、钩子、人物、节奏、为什么火），按视频缓存。"""

    __tablename__ = "video_analysis"
    video_id: Mapped[str] = mapped_column(ForeignKey("source_video.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String, default="")
    inputs: Mapped[list] = mapped_column(JSON, default=list)  # 实际用到的依据：文案 / 字幕 / 封面
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    """竞品热点分析报告。"""

    __tablename__ = "report"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="running")  # running done error
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Asset(Base):
    """素材库：演员（定妆照）、场景（场景图）、商品（用户上传的实拍图）。跨项目复用。"""

    __tablename__ = "asset"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)  # actor | scene | product
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")  # 外观 / 场景描述，生成关键帧时用
    images: Mapped[list] = mapped_column(JSON, default=list)  # 图片地址，第一张为主图
    tags: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # 商品：brand / model_sku / selling_points；演员：gender / age 等
    source: Mapped[str] = mapped_column(String, default="ai")  # ai | upload
    status: Mapped[str] = mapped_column(String, default="ready")  # ready | generating | error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Creator(Base):
    """达人雷达：可合作的 TikTok 达人。指标来自最近的公开视频；适配分、报价预估是算出来的，外联记录在 outreach。"""

    __tablename__ = "creator"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, default="TikTok")
    handle: Mapped[str] = mapped_column(String, index=True)  # 不带 @
    nickname: Mapped[str] = mapped_column(String, default="")
    market: Mapped[str] = mapped_column(String, default="尼日利亚")
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    bio: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String, default="")  # 简介里找到的邮箱
    avatar: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="搜索")  # 搜索 / 竞品合作 / 手动 / 演示
    found_by: Mapped[str] = mapped_column(String, default="")  # 搜索词 或 「@xiaomi_nigeria 的视频里 @ 过」
    tier: Mapped[str] = mapped_column(String, default="")  # 头部 / 肩部 / 腰部 / 尾部 / 素人
    stats: Mapped[dict] = mapped_column(JSON, default=dict)  # 播放中位数、互动率、更新频率、合作品牌……
    videos: Mapped[list] = mapped_column(JSON, default=list)  # 最近几条代表视频
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)  # 内容类型、受众、适合的产品线和理由（模型判断）
    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    best_product: Mapped[str] = mapped_column(String, default="")
    price: Mapped[dict] = mapped_column(JSON, default=dict)  # 单条视频报价预估区间（按 CPM 假设）
    status: Mapped[str] = mapped_column(String, default="new")  # new analyzing ok error
    error: Mapped[str] = mapped_column(String, default="")
    outreach: Mapped[dict] = mapped_column(JSON, default=dict)  # 外联（二期演示）：阶段、邮件往来、报价
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LibScript(Base):
    """剧本库：原创爆款剧本（结合本地热点头脑风暴 → 评审挑选 → 写分镜 → 40 人评测）。没写成分镜的创意也存着（status=concept）。"""

    __tablename__ = "lib_script"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch: Mapped[str] = mapped_column(String, index=True, default="")
    market: Mapped[str] = mapped_column(String, default="尼日利亚")
    product: Mapped[str] = mapped_column(String, default="")  # 产品线，如 TECNO Pova
    selling_point: Mapped[str] = mapped_column(String, default="")
    audience: Mapped[str] = mapped_column(String, default="")
    format: Mapped[str] = mapped_column(String, default="")  # 整活 / 挑战 / 反转短剧……
    title: Mapped[str] = mapped_column(String, default="")
    concept: Mapped[dict] = mapped_column(JSON, default=dict)  # 一句话创意、前 2 秒钩子、反转、卖点怎么落地、用了哪个热点、为什么会火、风险
    critic: Mapped[dict] = mapped_column(JSON, default=dict)  # 评审打分和意见
    shots: Mapped[list] = mapped_column(JSON, default=list)  # [[时间段, 画面, 口播, 中文], ...]
    evaluation: Mapped[dict] = mapped_column(JSON, default=dict)  # 40 人评测结果
    status: Mapped[str] = mapped_column(String, default="concept")  # concept writing ok evaluating error
    error: Mapped[str] = mapped_column(String, default="")
    used: Mapped[list] = mapped_column(JSON, default=list)  # 用到了哪些项目的画布
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
