from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Lane, Location, RefillOrder, Sale
from app.services.fill_engine import build_fill_lines, summarize
from app.services.freeze import build_frozen


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Location)) or 0) > 0:
        return
    loc = Location(code="VM-01", name="地铁口 A 点位", address="城东地铁 1 号口")
    db.add(loc)
    db.flush()
    lanes = [
        ("A1", "矿泉水", 20, 5, 0),
        ("A2", "可乐", 18, 18, 0),
        ("B1", "薯片", 12, 3, 2),
        ("B2", "巧克力", 15, 10, 5),
        ("C1", "能量棒", 10, 0, 0),
        ("C2", "口香糖", 24, 24, 2),
    ]
    lane_ids = []
    for slot, sku, cap, stock, transit in lanes:
        lane = Lane(location_id=loc.id, slot_no=slot, sku_name=sku, capacity=cap, stock=stock, in_transit=transit)
        db.add(lane)
        db.flush()
        lane_ids.append(lane.id)
    now = datetime(2026, 9, 16, 12, 0, 0)
    for i, lid in enumerate(lane_ids):
        db.add(Sale(lane_id=lid, qty=2 + i, sold_at=now - timedelta(hours=i)))
    db.flush()

    # 种子即冻结第 1 代补货单：之后改货道不影响这一单（A1 初始补量 15）
    _freeze_order(db, loc.id)
    db.commit()


def _freeze_order(db: Session, location_id: int, generation: int = 1) -> RefillOrder:
    lanes = db.scalars(
        select(Lane).where(Lane.location_id == location_id).order_by(Lane.slot_no)
    ).all()
    payload = [{"id": l.id, "slot_no": l.slot_no, "sku_name": l.sku_name,
                "capacity": l.capacity, "stock": l.stock, "in_transit": l.in_transit} for l in lanes]
    summary = summarize(build_fill_lines(payload))
    lines_text, sigs_text = build_frozen(summary["lines"])
    order = RefillOrder(location_id=location_id, generation=generation,
                        created_at=datetime.utcnow(), lines_json=lines_text,
                        line_sigs_json=sigs_text)
    db.add(order)
    db.flush()
    return order
