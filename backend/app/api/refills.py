from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Location, RefillOrder
from app.services.refill_service import (
    freeze_order, latest_order, live_gap_view, order_detail, order_list_row,
)
router = APIRouter(prefix="/refills", tags=["refills"])


def _require_location(location_id: int, db: Session) -> None:
    if not db.get(Location, location_id):
        raise HTTPException(404, "点位不存在")


@router.post("/run")
def run_refill(location_id: int = 1, db: Session = Depends(get_db)):
    """生成并冻结新单：此后改货道不再影响本单。"""
    _require_location(location_id, db)
    order = freeze_order(db, location_id)
    return order_detail(order)


@router.get("/orders")
def list_orders(location_id: int = 1, db: Session = Depends(get_db)):
    """历史单列表（新→旧）：只读冻结文本，漂移单带标记。"""
    _require_location(location_id, db)
    orders = db.scalars(
        select(RefillOrder).where(RefillOrder.location_id == location_id)
        .order_by(RefillOrder.id.desc())
    ).all()
    return [order_list_row(o) for o in orders]


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    """历史单详情：冻结世代，只读库内文本 + 漂移标注，绝不现算、绝不写回。"""
    order = db.get(RefillOrder, order_id)
    if not order:
        raise HTTPException(404, "补货单不存在")
    return order_detail(order)


@router.get("/latest")
def latest(location_id: int = 1, db: Session = Depends(get_db)):
    """最新有效单：最近一个冻结世代的快照读出。无单时返回空态，GET 不生成单。"""
    _require_location(location_id, db)
    order = latest_order(db, location_id)
    if not order:
        return {"id": None, "location_id": location_id, "lines": [], "empty": True,
                "total_fill": 0, "need_fill_count": 0, "full_count": 0, "overbooked_count": 0}
    return order_detail(order)


@router.get("/current")
def current_gap(location_id: int = 1, db: Session = Depends(get_db)):
    """「当前缺口」现算视图：跟最新货道，不落库、不带单号。"""
    _require_location(location_id, db)
    return live_gap_view(db, location_id)


@router.get("/full")
def full_lanes(location_id: int = 1, db: Session = Depends(get_db)):
    data = latest(location_id=location_id, db=db)
    return {"location_id": location_id, "lanes": [l for l in data["lines"] if l["status"] == "full"]}


@router.get("/summary")
def refill_summary(location_id: int = 1, db: Session = Depends(get_db)):
    data = latest(location_id=location_id, db=db)
    return {
        "location_id": location_id,
        "total_fill": data["total_fill"],
        "need_fill_count": data["need_fill_count"],
        "full_count": data["full_count"],
        "overbooked_count": data["overbooked_count"],
    }
