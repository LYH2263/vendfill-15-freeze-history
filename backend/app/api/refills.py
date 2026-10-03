import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane, Location, RefillOrder
from app.services.fill_engine import build_fill_lines, summarize
from app.services.freeze import build_frozen, read_frozen

router = APIRouter(prefix="/refills", tags=["refills"])


def _lanes_payload(db: Session, location_id: int) -> list[dict]:
    lanes = db.scalars(
        select(Lane).where(Lane.location_id == location_id).order_by(Lane.slot_no)
    ).all()
    return [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
             "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit} for l in lanes]


def compute_current(db: Session, location_id: int) -> dict:
    """货道现算世代：永远读最新货道，不落库、不影响任何历史单。"""
    summary = summarize(build_fill_lines(_lanes_payload(db, location_id)))
    return {"id": None, "location_id": location_id, "generation": None,
            "generation_kind": "current", "frozen": False, **summary}


def _next_generation(db: Session, location_id: int) -> int:
    top = db.scalar(
        select(func.coalesce(func.max(RefillOrder.generation), 0))
        .where(RefillOrder.location_id == location_id)
    )
    return int(top or 0) + 1


def _frozen_detail(order: RefillOrder) -> dict:
    """把一单历史快照原样读出；合计与行都跟库内文本（含脏文本），另附漂移标注。"""
    fr = read_frozen(order.lines_json, order.line_sigs_json)
    lines = fr["lines"]
    lines_drift = fr["lines_drift"]
    for l in lines:
        key = str(l.get("lane_id"))
        if key in lines_drift:
            l["line_drift"] = True
            l["line_drift_reason"] = lines_drift[key]
        else:
            l["line_drift"] = False

    if fr["lines_corrupt"]:
        # 行 JSON 已被截断到无法解析：合计无法从脏文本得出，置空而非现算伪造
        totals = {"total_fill": None, "need_fill_count": None,
                  "full_count": None, "overbooked_count": None}
    else:
        totals = {
            "total_fill": sum(int(l.get("fill_qty") or 0) for l in lines),
            "need_fill_count": sum(1 for l in lines if l.get("status") == "need_fill"),
            "full_count": sum(1 for l in lines if l.get("status") == "full"),
            "overbooked_count": sum(1 for l in lines if l.get("status") == "overbooked"),
        }

    return {
        "id": order.id,
        "location_id": order.location_id,
        "generation": order.generation,
        "generation_kind": "frozen",
        "frozen": True,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "lines": lines,
        "drift": fr["drift"],
        "lines_drift": lines_drift,
        "missing_lines": fr["missing_lines"],
        "extra_lines": fr["extra_lines"],
        "lines_corrupt": fr["lines_corrupt"],
        "raw_lines_text": fr["raw_lines_text"],
        **totals,
    }


@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    """显式生成新一代并冻结。只在此时按当前货道计算一次，之后不再回写。"""
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "点位不存在")
    summary = summarize(build_fill_lines(_lanes_payload(db, location_id)))
    lines_text, sigs_text = build_frozen(summary["lines"])
    order = RefillOrder(
        location_id=location_id,
        generation=_next_generation(db, location_id),
        created_at=datetime.utcnow(),
        lines_json=lines_text,
        line_sigs_json=sigs_text,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _frozen_detail(order)


@router.get("")
def list_orders(location_id: int = 1, db: Session = Depends(get_db)):
    """历史单列表：纯读。合计跟库内文本，漂移单独标出；绝不写回。"""
    orders = db.scalars(
        select(RefillOrder)
        .where(RefillOrder.location_id == location_id)
        .order_by(RefillOrder.generation.desc(), RefillOrder.id.desc())
    ).all()
    out = []
    for o in orders:
        d = _frozen_detail(o)
        out.append({
            "id": d["id"], "location_id": d["location_id"], "generation": d["generation"],
            "created_at": d["created_at"], "frozen": True,
            "total_fill": d["total_fill"], "need_fill_count": d["need_fill_count"],
            "full_count": d["full_count"], "overbooked_count": d["overbooked_count"],
            "drift": d["drift"], "lines_corrupt": d["lines_corrupt"],
            "drift_line_count": len(d["lines_drift"]) + len(d["missing_lines"]),
        })
    return out


@router.get("/current")
def current_gap(location_id: int = 1, db: Session = Depends(get_db)):
    """当前缺口视图：货道现算，跟随最新库存/在途/容量，不生成历史单。"""
    if not db.get(Location, location_id):
        raise HTTPException(404, "点位不存在")
    return compute_current(db, location_id)


@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    """最新一次生成的冻结单；纯读，不存在返回 404，不代客生成。"""
    order = db.scalars(
        select(RefillOrder)
        .where(RefillOrder.location_id == location_id)
        .order_by(RefillOrder.generation.desc(), RefillOrder.id.desc())
    ).first()
    if not order:
        raise HTTPException(404, "暂无历史补货单，请先生成")
    return _frozen_detail(order)


@router.get("/{order_id}")
def order_detail(order_id: int, db: Session = Depends(get_db)):
    """历史单详情：冻结世代。改货道不影响这里；库内被改脏则原样显示并标漂移。"""
    order = db.get(RefillOrder, order_id)
    if not order:
        raise HTTPException(404, "补货单不存在")
    return _frozen_detail(order)


@router.get("/view/full")
def full_lanes(location_id: int = 1, db: Session = Depends(get_db)):
    data = compute_current(db, location_id)
    return {"location_id": location_id, "generation_kind": "current",
            "lanes": [l for l in data["lines"] if l["status"] == "full"]}


@router.get("/view/summary")
def refill_summary(location_id: int = 1, db: Session = Depends(get_db)):
    data = compute_current(db, location_id)
    return {
        "location_id": location_id,
        "generation_kind": "current",
        "total_fill": data["total_fill"],
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
    }
