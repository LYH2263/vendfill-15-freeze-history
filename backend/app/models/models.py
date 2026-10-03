from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(256), default="")

class Lane(Base):
    __tablename__ = "lanes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    slot_no: Mapped[str] = mapped_column(String(16))
    sku_name: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, default=0)

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lane_id: Mapped[int] = mapped_column(ForeignKey("lanes.id"))
    qty: Mapped[int] = mapped_column(Integer)
    sold_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RefillOrder(Base):
    __tablename__ = "refill_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 冻结快照：生成当时的逐行补量/状态，之后货道再怎么改都不回写这里
    lines_json: Mapped[str] = mapped_column(Text, default="[]")
    # 逐行签名：读时用它判定库内行文本是否被截短/改脏（只标注，不修复）
    line_sigs_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
