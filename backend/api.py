import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import update

from claimer import start as start_claimer
from models import (
    Base,
    ConvergenceLog,
    Nameplate,
    PlateEvent,
    SessionLocal,
    engine,
    ensure_immutable_guard,
    event_dict,
    plate_dict,
    row_dict,
)

SECRET = os.environ.get("JWT_SECRET", "tunnelconv-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

app = Flask(__name__)


def lock_plate(db, code: str):
    """在当前事务内对目标铭牌取写锁并返回行。

    用“同值 UPDATE”取锁，跨 PG/SQLite 行为一致：
    PG 上是行级排他锁（与并发退役/改号排队），SQLite 上升级为写锁串行提交。
    落库一律以锁后读回的在册行为准，杜绝落库前偷换号。
    """
    db.execute(
        update(Nameplate).where(Nameplate.code == code).values(status=Nameplate.status)
    )
    return db.query(Nameplate).filter(Nameplate.code == code).first()


def seed():
    Base.metadata.create_all(engine)
    ensure_immutable_guard(engine)
    db = SessionLocal()
    try:
        if db.query(Nameplate).count() > 0:
            return
        now = datetime.now(timezone.utc)

        def plate(code, section, status, retired_at=None):
            return Nameplate(
                code=code,
                section=section,
                status=status,
                created_by="surveyor",
                created_at=now,
                retired_at=retired_at,
            )

        active_12180 = plate("J-12180", "K12+180 甲断面", "active")
        active_20050 = plate("J-20050", "K20+050 甲断面", "active")
        # 一张已退役牌：退役前交过的旧单仍留着它的号，只不允许再交新单。
        retired_18040 = plate(
            "J-18040", "K18+040 乙断面", "retired", retired_at=now
        )
        db.add_all([active_12180, active_20050, retired_18040])

        def event(code, action, detail):
            return PlateEvent(
                code=code,
                action=action,
                detail=detail,
                operator="surveyor",
                created_at=now,
            )

        # 履历与名册改动同事务写齐。
        db.add_all(
            [
                event("J-12180", "register", "号段入册：K12+180 甲断面"),
                event("J-20050", "register", "号段入册：K20+050 甲断面"),
                event("J-18040", "register", "号段入册：K18+040 乙断面"),
                event("J-18040", "retire", "铭牌退役，旧绑定保留"),
            ]
        )

        db.add(
            ConvergenceLog(
                plate_code="J-12180",
                section="K12+180 甲断面",
                chainage="K12+180 甲断面",
                delta_mm=1.2,
                status="done",
                verdict="合格",
                reason="收敛 1.2 mm 在 ±3.0 mm 以内",
                created_by="surveyor",
                created_at=now,
                processed_at=now,
            )
        )
        # 退役前的历史单：号随旧单永久保留。
        db.add(
            ConvergenceLog(
                plate_code="J-18040",
                section="K18+040 乙断面",
                chainage="K18+040 乙断面",
                delta_mm=5.6,
                status="done",
                verdict="超限",
                reason="收敛 5.6 mm 超过 ±3.0 mm",
                created_by="surveyor",
                created_at=now,
                processed_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


seed()
start_claimer()


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth[7:].strip(), SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def require_writer(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify({"detail": "未登录"}), 401
        if user["role"] != "writer":
            # 巡检岗：能读名册，不能改册、不能报送。
            return jsonify({"detail": "巡检岗只读名册，不能改册或报送"}), 403
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "tunnel-convergence-desk"})


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        return jsonify({"detail": "用户名或密码错误"}), 401
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp}, SECRET, algorithm="HS256"
    )
    return jsonify({"access_token": token, "username": username, "role": user["role"]})


@app.get("/api/logs")
@require_login
def list_logs():
    db = SessionLocal()
    try:
        rows = db.query(ConvergenceLog).order_by(ConvergenceLog.id.desc()).all()
        return jsonify([row_dict(r) for r in rows])
    finally:
        db.close()


@app.get("/api/plates")
@require_login
def list_plates():
    """铭牌册：巡检岗与测量员都可读，可按在役/退役过滤。"""
    status = (request.args.get("status") or "").strip()
    db = SessionLocal()
    try:
        q = db.query(Nameplate)
        if status in ("active", "retired"):
            q = q.filter(Nameplate.status == status)
        rows = q.order_by(Nameplate.code).all()
        return jsonify([plate_dict(r) for r in rows])
    finally:
        db.close()


@app.get("/api/plates/events")
@require_login
def list_plate_events():
    code = (request.args.get("code") or "").strip()
    db = SessionLocal()
    try:
        q = db.query(PlateEvent)
        if code:
            q = q.filter(PlateEvent.code == code)
        rows = q.order_by(PlateEvent.id.desc()).all()
        return jsonify([event_dict(r) for r in rows])
    finally:
        db.close()


@app.post("/api/plates")
@require_writer
def register_plate():
    """测量员维护号段：新号入册；名册行与履历同事务一次写齐。"""
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    section = (body.get("section") or "").strip()
    if not code:
        return jsonify({"detail": "铭牌号不能为空"}), 400
    if not section:
        return jsonify({"detail": "绑定断面不能为空"}), 400
    db = SessionLocal()
    try:
        if db.query(Nameplate).filter(Nameplate.code == code).first():
            return jsonify({"detail": f"铭牌 {code} 已在册"}), 409
        now = datetime.now(timezone.utc)
        db.add(
            Nameplate(
                code=code,
                section=section,
                status="active",
                created_by=g.user["username"],
                created_at=now,
            )
        )
        db.add(
            PlateEvent(
                code=code,
                action="register",
                detail=f"号段入册：{section}",
                operator=g.user["username"],
                created_at=now,
            )
        )
        db.commit()  # 名册改动与履历一次写齐，要么都成要么都不成。
        row = db.query(Nameplate).filter(Nameplate.code == code).first()
        return jsonify(plate_dict(row)), 201
    finally:
        db.close()


@app.post("/api/plates/<code>/retire")
@require_writer
def retire_plate(code):
    """铭牌退役：只改册状态+写履历，绝不回改任何旧单上的号。"""
    code = code.strip()
    db = SessionLocal()
    try:
        # 与报送事务抢同一把行锁：正在报送的单先放行，退役在其后生效。
        row = lock_plate(db, code)
        if row is None:
            return jsonify({"detail": f"铭牌 {code} 不在册"}), 404
        if row.status == "retired":
            return jsonify({"detail": f"铭牌 {code} 已处于退役"}), 409
        now = datetime.now(timezone.utc)
        row.status = "retired"
        row.retired_at = now
        db.add(
            PlateEvent(
                code=code,
                action="retire",
                detail="铭牌退役，旧绑定保留",
                operator=g.user["username"],
                created_at=now,
            )
        )
        db.commit()
        return jsonify(plate_dict(row))
    finally:
        db.close()


@app.post("/api/logs")
@require_writer
def create_log():
    body = request.get_json(silent=True) or {}
    code = (body.get("plate_code") or "").strip()
    if not code:
        # 没有在役铭牌不许报测缝。
        return jsonify({"detail": "没有在役铭牌不许报测缝，请点选在役铭牌号"}), 400
    try:
        delta_mm = float(body.get("delta_mm"))
    except (TypeError, ValueError):
        return jsonify({"detail": "收敛值必须是数字"}), 400

    db = SessionLocal()
    try:
        # 事务内锁住铭牌行再判定，杜绝“落库前偷换号”：
        # 并发的退役/改动先被这把写锁挡住（与其排队），落库一律以库内读回的号为准。
        plate = lock_plate(db, code)
        if plate is None:
            # 查无此号：网页、直连接口、伪造号一视同仁拒绝。
            return (
                jsonify({"detail": f"铭牌 {code} 不在册，没有在役铭牌不许报测缝"}),
                400,
            )
        if plate.status != "active":
            # 提交瞬间该号被退役：整份退回，不产生半成品单。
            return (
                jsonify(
                    {
                        "detail": (
                            f"铭牌 {code} 已退役，整份退回；"
                            "该号旧单仍留原来的号，但不能再交新单"
                        )
                    }
                ),
                400,
            )

        # 关键：断面与号都取自库内锁定行，不信请求体里可能被旁路篡改的文本。
        row = ConvergenceLog(
            plate_code=plate.code,
            section=plate.section,
            chainage=plate.section,
            delta_mm=delta_mm,
            status="pending",
            created_by=g.user["username"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return jsonify(row_dict(row)), 201
    finally:
        db.close()
