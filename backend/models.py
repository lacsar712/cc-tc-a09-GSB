import os
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54401/tunnelconv")
engine = create_engine(DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Nameplate(Base):
    """铭牌册条目。status 只有 active（在役）/ retired（退役）。"""

    __tablename__ = "nameplates"

    plate_no: Mapped[str] = mapped_column(String(16), primary_key=True)
    chainage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["NameplateEvent"]] = relationship(
        back_populates="plate", order_by="NameplateEvent.id"
    )


class NameplateEvent(Base):
    """铭牌履历：登记 / 绑定测缝单 / 退役。名册任何改动必须同事务追加一行。"""

    __tablename__ = "nameplate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_no: Mapped[str] = mapped_column(
        String(16), ForeignKey("nameplates.plate_no"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # register | bind | retire
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plate: Mapped[Nameplate] = relationship(back_populates="events")


class ConvergenceLog(Base):
    __tablename__ = "convergence_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_no: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("nameplates.plate_no"), nullable=True
    )
    chainage: Mapped[str] = mapped_column(String, nullable=False)
    delta_mm: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def plate_dict(p: Nameplate) -> dict:
    return {
        "plate_no": p.plate_no,
        "chainage": p.chainage,
        "status": p.status,
        "created_by": p.created_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "retired_at": p.retired_at.isoformat() if p.retired_at else None,
        "retired_by": p.retired_by,
        "retire_reason": p.retire_reason,
    }


def event_dict(e: NameplateEvent) -> dict:
    return {
        "id": e.id,
        "plate_no": e.plate_no,
        "kind": e.kind,
        "detail": e.detail,
        "log_id": e.log_id,
        "actor": e.actor,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def row_dict(row: ConvergenceLog) -> dict:
    return {
        "id": row.id,
        "plate_no": row.plate_no,
        "chainage": row.chainage,
        "delta_mm": row.delta_mm,
        "status": row.status,
        "verdict": row.verdict,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }


def ensure_schema():
    """建表并给基线旧库补 plate_no 列（开发卷升级用）。"""
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("convergence_logs")}
    if "plate_no" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE convergence_logs ADD COLUMN plate_no VARCHAR(16)"))
