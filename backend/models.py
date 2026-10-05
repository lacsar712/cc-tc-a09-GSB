import os
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://app:app@localhost:54401/tunnelconv"
)

# 本地无 Docker/PG 时可用 sqlite 做端到端验证：DATABASE_URL=sqlite:///./dev.db
if DSN.startswith("sqlite"):
    # busy timeout 让写冲突等待而非立即报 locked，近似串行化提交。
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    connect_args = {}

engine = create_engine(DSN, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Nameplate(Base):
    """铭牌册：一个号对应一个固定断面；在役可绑，退役不可再绑。

    一旦该号绑过测缝单，事后退役绝不回改旧单上的号
    （旧单仍留原来的号），并由数据库触发器硬挡任何改号。
    """

    __tablename__ = "nameplates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlateEvent(Base):
    """铭牌履历：入册 / 退役，与名册改动同事务一次写齐。"""

    __tablename__ = "plate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # register/retire
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ConvergenceLog(Base):
    __tablename__ = "convergence_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 落库的号以“事务内锁行后读回”的在册号为准，不信前端/body 文本，
    # 这样旁路直调或提交瞬间被偷换号都绑不错。
    plate_code: Mapped[str] = mapped_column(String(32), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    chainage: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_mm: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def plate_dict(row: Nameplate) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "section": row.section,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
    }


def event_dict(row: PlateEvent) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "detail": row.detail,
        "action": row.action,
        "operator": row.operator,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# 认领线程/接口按 row_dict 取数。
def row_dict(row: ConvergenceLog) -> dict:
    return {
        "id": row.id,
        "plate_code": row.plate_code,
        "section": row.section,
        "chainage": row.chainage,
        "delta_mm": row.delta_mm,
        "status": row.status,
        "verdict": row.verdict,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }


# ---------------------------------------------------------------------------
# 数据库层硬约束：绑过单的号不可改、不可解绑。
# 即便有人绕过网页和接口直连落库（旁路 / SQL），也改不动旧绑定。
# 在 create_all 之后调用一次；幂等。
# ---------------------------------------------------------------------------
_SQLITE_GUARD = """
CREATE TRIGGER IF NOT EXISTS trg_log_plate_immutable
AFTER UPDATE ON convergence_logs
FOR EACH ROW
WHEN NEW.plate_code <> OLD.plate_code OR NEW.section <> OLD.section
BEGIN
    SELECT RAISE(ABORT, '铭牌一旦绑上本单，退役后也不得改旧绑定');
END;
"""

_PG_GUARD_FN = """
CREATE OR REPLACE FUNCTION convergence_log_plate_immutable()
RETURNS trigger AS $$
BEGIN
    IF NEW.plate_code <> OLD.plate_code OR NEW.section <> OLD.section THEN
        RAISE EXCEPTION '铭牌一旦绑上本单，退役后也不得改旧绑定';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_PG_GUARD_TRG = """
DROP TRIGGER IF EXISTS trg_log_plate_immutable ON convergence_logs;
CREATE TRIGGER trg_log_plate_immutable
    BEFORE UPDATE ON convergence_logs
    FOR EACH ROW
    EXECUTE FUNCTION convergence_log_plate_immutable();
"""


def ensure_immutable_guard(target_engine=engine) -> None:
    """对所有新连接生效的行级触发器：旧绑定改号即中止该事务。"""
    with target_engine.begin() as conn:
        if target_engine.dialect.name == "sqlite":
            conn.exec_driver_sql(_SQLITE_GUARD)
        else:
            conn.exec_driver_sql(_PG_GUARD_FN)
            conn.exec_driver_sql(_PG_GUARD_TRG)

