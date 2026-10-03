"""补货单的三个世代严格分离，混代即废：

1. freeze_order   —— 生成即冻结：现算一次写入 lines_json + integrity_json，此后永不改写。
2. order_detail / order_list_row —— 历史世代：只读库内冻结文本，逐行校验漂移；
   漂移只标注「行已漂移」，原样返回脏数据，禁止不声张地写回修好。
3. live_gap_view  —— 现算世代：跟当前货道表实时计算，不落库、不带单号。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Lane, RefillOrder
from app.services.fill_engine import build_fill_lines, summarize

TOTAL_KEYS = ("total_fill", "need_fill_count", "full_count", "overbooked_count")


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def line_hash(line: dict) -> str:
    return _sha(_canon(line))


def _build_integrity(summary: dict) -> str:
    totals = {k: summary[k] for k in TOTAL_KEYS}
    return json.dumps({
        "algo": "sha256",
        "lines": {str(l["lane_id"]): line_hash(l) for l in summary["lines"]},
        "totals": _sha(_canon(totals)),
    }, ensure_ascii=False)


def _lane_payloads(db: Session, location_id: int) -> list[dict]:
    lanes = db.scalars(
        select(Lane).where(Lane.location_id == location_id).order_by(Lane.slot_no)
    ).all()
    return [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
             "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit} for l in lanes]


def freeze_order(db: Session, location_id: int) -> RefillOrder:
    """按当前货道现算并冻结成单。这是补货单的唯一写路径。"""
    summary = summarize(build_fill_lines(_lane_payloads(db, location_id)))
    order = RefillOrder(
        location_id=location_id,
        created_at=datetime.utcnow(),
        lines_json=json.dumps(summary, ensure_ascii=False),
        integrity_json=_build_integrity(summary),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def live_gap_view(db: Session, location_id: int) -> dict:
    """「当前缺口」现算视图：跟最新货道数据，不落库、不属于任何已冻结世代。"""
    summary = summarize(build_fill_lines(_lane_payloads(db, location_id)))
    return {"id": None, "location_id": location_id, "live": True, **summary}


def _check_drift(order: RefillOrder, data: dict) -> tuple[list[dict], bool, bool]:
    """逐行比对库内文本与生成时哈希。返回 (带 drifted 标记的行, 是否有漂移, 是否校验不了)。"""
    if not order.integrity_json:
        return list(data.get("lines", [])), False, True
    integrity = json.loads(order.integrity_json)
    expected: dict = integrity.get("lines", {})
    lines = []
    drift = False
    seen: set[str] = set()
    for raw in data.get("lines", []):
        line = dict(raw)
        key = str(line.get("lane_id"))
        seen.add(key)
        line["drifted"] = key not in expected or expected[key] != line_hash(raw)
        drift = drift or line["drifted"]
        lines.append(line)
    if seen != set(expected):  # 行被整行删掉或塞入新行
        drift = True
    totals = {k: data.get(k) for k in TOTAL_KEYS}
    if integrity.get("totals") != _sha(_canon(totals)):
        drift = True
    return lines, drift, False


def order_detail(order: RefillOrder) -> dict:
    """历史单详情：原样读出库内冻结文本并标注漂移，绝不现算覆盖、绝不写回修好。"""
    base = {"id": order.id, "location_id": order.location_id,
            "created_at": order.created_at.isoformat(), "frozen": True}
    try:
        data = json.loads(order.lines_json)
    except (json.JSONDecodeError, TypeError):
        # 库内文本被截短/改脏到无法解析：仍把脏文本原样交出，标漂移。
        return {**base, "lines": [], "corrupt": True, "has_drift": True,
                "raw": order.lines_json, **{k: 0 for k in TOTAL_KEYS}}
    lines, drift, unchecked = _check_drift(order, data)
    return {**base, "lines": lines, "corrupt": False, "has_drift": drift,
            "integrity_unchecked": unchecked,
            **{k: data.get(k, 0) for k in TOTAL_KEYS}}


def order_list_row(order: RefillOrder) -> dict:
    """历史列表行：同样只读冻结文本，供列表展示与漂移徽章。"""
    d = order_detail(order)
    return {"id": d["id"], "location_id": d["location_id"], "created_at": d["created_at"],
            "has_drift": d["has_drift"], "corrupt": d["corrupt"],
            **{k: d[k] for k in TOTAL_KEYS}}


def latest_order(db: Session, location_id: int) -> RefillOrder | None:
    return db.scalars(
        select(RefillOrder).where(RefillOrder.location_id == location_id)
        .order_by(RefillOrder.id.desc())
    ).first()
