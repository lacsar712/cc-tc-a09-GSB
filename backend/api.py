import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, request
from jose import JWTError, jwt
from passlib.context import CryptContext

from claimer import start as start_claimer
from models import (
    ConvergenceLog,
    Nameplate,
    NameplateEvent,
    SessionLocal,
    ensure_schema,
    event_dict,
    plate_dict,
    row_dict,
)
from plates import normalize_plate_no, valid_plate_no

SECRET = os.environ.get("JWT_SECRET", "tunnelconv-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

app = Flask(__name__)


def now():
    return datetime.now(timezone.utc)


def seed():
    """铭牌、履历、历史测缝单一次写齐（同一事务）。"""
    ensure_schema()
    db = SessionLocal()
    try:
        if db.query(Nameplate).count() > 0:
            return
        ts = now()
        # MP-0001 在役；MP-0002 退役（其旧测缝单保留原绑定）；MP-0003 在役
        p1 = Nameplate(
            plate_no="MP-0001", chainage="K12+180", status="active",
            created_by="system", created_at=ts,
        )
        p2 = Nameplate(
            plate_no="MP-0002", chainage="K18+040", status="retired",
            created_by="system", created_at=ts,
            retired_at=ts, retired_by="system", retire_reason="断面废弃，种子退役铭牌",
        )
        p3 = Nameplate(
            plate_no="MP-0003", chainage="K20+050", status="active",
            created_by="system", created_at=ts,
        )
        db.add_all([p1, p2, p3])
        db.flush()
        db.add_all(
            [
                NameplateEvent(plate_no="MP-0001", kind="register", detail="种子在役铭牌",
                               actor="system", created_at=ts),
                NameplateEvent(plate_no="MP-0002", kind="register", detail="种子铭牌",
                               actor="system", created_at=ts),
                NameplateEvent(plate_no="MP-0002", kind="retire", detail="断面废弃，种子退役铭牌",
                               actor="system", created_at=ts),
                NameplateEvent(plate_no="MP-0003", kind="register", detail="种子在役铭牌",
                               actor="system", created_at=ts),
            ]
        )
        log1 = ConvergenceLog(
            plate_no="MP-0001", chainage="K12+180", delta_mm=1.2, status="done",
            verdict="合格", reason="收敛 1.2 mm 在 ±3.0 mm 以内",
            created_by="surveyor", created_at=ts, processed_at=ts,
        )
        log2 = ConvergenceLog(
            plate_no="MP-0002", chainage="K18+040", delta_mm=5.6, status="done",
            verdict="超限", reason="收敛 5.6 mm 超过 ±3.0 mm",
            created_by="surveyor", created_at=ts, processed_at=ts,
        )
        db.add_all([log1, log2])
        db.flush()
        db.add_all(
            [
                NameplateEvent(plate_no="MP-0001", kind="bind", detail="种子历史测缝单",
                               log_id=log1.id, actor="surveyor", created_at=ts),
                NameplateEvent(plate_no="MP-0002", kind="bind", detail="种子历史测缝单（退役前绑定）",
                               log_id=log2.id, actor="surveyor", created_at=ts),
            ]
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
    exp = now() + timedelta(hours=8)
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


@app.post("/api/logs")
@require_writer
def create_log():
    """报送测缝：必须绑定在役铭牌。

    强制全部在服务端同一事务内完成，不依赖网页：
    1) 铭牌号服务端归一化（防空白/大小写旁路），号形态非法直接拒；
    2) SELECT ... FOR UPDATE 取库内铭牌行，缺号 / 已退役一律拒，整份退回；
    3) 断面取自库内铭牌而非请求体，单号落库为库内规范号（防落库前偷换号）；
    4) 测缝单与绑定履历同一事务写入。
    """
    body = request.get_json(silent=True) or {}
    plate_no = normalize_plate_no(body.get("plate_no"))
    if not valid_plate_no(plate_no):
        return jsonify({"detail": "必须绑定形态为 MP-0000 的铭牌号"}), 400
    try:
        delta_mm = float(body.get("delta_mm"))
    except (TypeError, ValueError):
        return jsonify({"detail": "收敛值必须是数字"}), 400

    db = SessionLocal()
    try:
        plate = (
            db.query(Nameplate)
            .filter(Nameplate.plate_no == plate_no)
            .with_for_update()
            .first()
        )
        if plate is None:
            return jsonify({"detail": f"铭牌 {plate_no} 不在铭牌册，不许报测缝"}), 400
        if plate.status != "active":
            # 整份退回：不落任何测缝单、不写履历
            return jsonify({"detail": f"铭牌 {plate_no} 已退役，整份退回，不收该测缝单"}), 409

        row = ConvergenceLog(
            plate_no=plate.plate_no,  # 一律用库内规范号
            chainage=plate.chainage,  # 断面取自铭牌册，忽略请求体里的任何值
            delta_mm=delta_mm,
            status="pending",
            created_by=g.user["username"],
            created_at=now(),
        )
        db.add(row)
        db.flush()  # 取 row.id 写履历
        db.add(
            NameplateEvent(
                plate_no=plate.plate_no,
                kind="bind",
                detail=f"报送测缝单，断面 {plate.chainage}，收敛 {delta_mm} mm",
                log_id=row.id,
                actor=g.user["username"],
                created_at=now(),
            )
        )
        db.commit()
        db.refresh(row)
        return jsonify(row_dict(row)), 201
    finally:
        db.close()


@app.get("/api/plates")
@require_login
def list_plates():
    db = SessionLocal()
    try:
        plates = db.query(Nameplate).order_by(Nameplate.plate_no).all()
        return jsonify(
            {
                "active": [plate_dict(p) for p in plates if p.status == "active"],
                "retired": [plate_dict(p) for p in plates if p.status == "retired"],
            }
        )
    finally:
        db.close()


@app.get("/api/plates/events")
@require_login
def list_plate_events():
    plate_no = normalize_plate_no(request.args.get("plate_no"))
    db = SessionLocal()
    try:
        q = db.query(NameplateEvent).order_by(NameplateEvent.id.desc())
        if plate_no:
            q = q.filter(NameplateEvent.plate_no == plate_no)
        return jsonify([event_dict(e) for e in q.limit(200).all()])
    finally:
        db.close()


@app.post("/api/plates")
@require_writer
def register_plate():
    """号段维护：登记新在役铭牌；名册条目与履历一次写齐。"""
    body = request.get_json(silent=True) or {}
    plate_no = normalize_plate_no(body.get("plate_no"))
    chainage = (body.get("chainage") or "").strip()
    if not valid_plate_no(plate_no):
        return jsonify({"detail": "铭牌号必须形如 MP-0000（MP-0000~MP-9999）"}), 400
    if not chainage:
        return jsonify({"detail": "断面桩号不能为空"}), 400

    db = SessionLocal()
    try:
        existing = db.query(Nameplate).filter(Nameplate.plate_no == plate_no).first()
        if existing is not None:
            return jsonify({"detail": f"铭牌 {plate_no} 已在册（{existing.status}），不能重复登记"}), 409
        plate = Nameplate(
            plate_no=plate_no,
            chainage=chainage,
            status="active",
            created_by=g.user["username"],
            created_at=now(),
        )
        db.add(plate)
        db.add(
            NameplateEvent(
                plate_no=plate_no, kind="register",
                detail=f"登记在役铭牌，断面 {chainage}",
                actor=g.user["username"], created_at=now(),
            )
        )
        db.commit()
        db.refresh(plate)
        return jsonify(plate_dict(plate)), 201
    finally:
        db.close()


@app.post("/api/plates/<raw_no>/retire")
@require_writer
def retire_plate(raw_no):
    """退役整份生效：状态与履历同一事务，任一步失败整体退回（仍在役）。"""
    plate_no = normalize_plate_no(raw_no)
    if not valid_plate_no(plate_no):
        return jsonify({"detail": "铭牌号必须形如 MP-0000"}), 400
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip() or "未填写退役原因"

    db = SessionLocal()
    try:
        plate = (
            db.query(Nameplate)
            .filter(Nameplate.plate_no == plate_no)
            .with_for_update()
            .first()
        )
        if plate is None:
            return jsonify({"detail": f"铭牌 {plate_no} 不在铭牌册"}), 404
        if plate.status == "retired":
            return jsonify({"detail": f"铭牌 {plate_no} 已退役，退役不可改"}), 409

        plate.status = "retired"
        plate.retired_at = now()
        plate.retired_by = g.user["username"]
        plate.retire_reason = reason
        db.add(
            NameplateEvent(
                plate_no=plate_no, kind="retire", detail=reason,
                actor=g.user["username"], created_at=now(),
            )
        )
        db.commit()
        db.refresh(plate)
        return jsonify(plate_dict(plate))
    finally:
        db.close()
