from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Lane
from app.services.fill_engine import compute_gap
router = APIRouter(prefix="/lanes", tags=["lanes"])

def _row(r: Lane) -> dict:
    return {"id": r.id, "location_id": r.location_id, "slot_no": r.slot_no, "sku_name": r.sku_name,
            "capacity": r.capacity, "stock": r.stock, "in_transit": r.in_transit,
            "gap": compute_gap(r.capacity, r.stock, r.in_transit),
            "fill_pct": round(r.stock / r.capacity * 100, 1) if r.capacity else 0}

@router.get("")
def list_lanes(location_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Lane).order_by(Lane.slot_no)
    if location_id is not None: q = q.where(Lane.location_id == location_id)
    return [_row(r) for r in db.scalars(q).all()]

class LanePatch(BaseModel):
    stock: int | None = Field(default=None, ge=0)
    in_transit: int | None = Field(default=None, ge=0)
    capacity: int | None = Field(default=None, ge=0)

@router.patch("/{lane_id}")
def patch_lane(lane_id: int, body: LanePatch, db: Session = Depends(get_db)):
    """改货道库存/在途/容量：只写 lanes 表。已冻结的历史补货单绝不被波及。"""
    lane = db.get(Lane, lane_id)
    if not lane: raise HTTPException(404, "货道不存在")
    for field in ("stock", "in_transit", "capacity"):
        value = getattr(body, field)
        if value is not None: setattr(lane, field, value)
    db.commit(); db.refresh(lane)
    return _row(lane)
