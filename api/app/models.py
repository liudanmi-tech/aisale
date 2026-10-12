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
