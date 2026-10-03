from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Lane
from app.services.fill_engine import compute_gap

router = APIRouter(prefix="/lanes", tags=["lanes"])


class LanePatch(BaseModel):
    # 货道现算世代的输入：改这里只影响「当前缺口」与后续新生成的单，不回写任何历史单
    stock: int | None = None
    in_transit: int | None = None
    capacity: int | None = None


def _lane_out(r: Lane) -> dict:
    gap = compute_gap(r.capacity, r.stock, r.in_transit)
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit, "gap": gap,
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}


@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None:
        q = q.where(Lane.location_id == location_id)
    return [_lane_out(r) for r in db.scalars(q).all()]


@router.patch("/{lane_id}")
def update_lane(lane_id: int, patch: LanePatch, db: Session = Depends(get_db)):
    lane = db.get(Lane, lane_id)
    if not lane:
        raise HTTPException(404, "货道不存在")
    for field in ("stock", "in_transit", "capacity"):
        val = getattr(patch, field)
        if val is not None:
            if val < 0:
                raise HTTPException(422, f"{field} 不能为负")
            setattr(lane, field, val)
    db.commit()
    db.refresh(lane)
    return _lane_out(lane)
