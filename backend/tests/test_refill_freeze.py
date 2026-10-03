"""历史补货单冻结：分世代、漂移标注、禁批量改写、禁写回修好。"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import RefillOrder
from app.services.seed import seed_if_empty

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    seed_if_empty(db)  # 种子含首个冻结单：A1 容量20/库存5/在途0 → 补量 15
    db.close()
    yield TestClient(app)  # 不进 lifespan，避免连真实库
    Base.metadata.drop_all(bind=engine)


def _a1(payload: dict) -> dict:
    return next(l for l in payload["lines"] if l["slot_no"] == "A1")


def _dirty_order_lines(order_id: int, mutate) -> None:
    db = TestingSessionLocal()
    order = db.get(RefillOrder, order_id)
    data = json.loads(order.lines_json)
    mutate(data)
    order.lines_json = json.dumps(data, ensure_ascii=False)
    db.commit()
    db.close()


def test_old_order_frozen_new_order_shrinks(client):
    # 种子首单 A1 补量 15
    first_id = client.get("/api/refills/orders?location_id=1").json()[0]["id"]
    assert _a1(client.get(f"/api/refills/orders/{first_id}").json())["fill_qty"] == 15

    # A1 库存改大 5 → 12
    lane_id = _a1(client.get(f"/api/refills/orders/{first_id}").json())["lane_id"]
    client.patch(f"/api/lanes/{lane_id}", json={"stock": 12})

    # 旧单详情仍是生成当时的补量与库存快照
    old = _a1(client.get(f"/api/refills/orders/{first_id}").json())
    assert old["fill_qty"] == 15 and old["stock"] == 5

    # 再生成的新单才反映新缺口 20-12=8，两单并排可对
    second = client.post("/api/refills/run?location_id=1").json()
    assert _a1(second)["fill_qty"] == 8
    ids = [o["id"] for o in client.get("/api/refills/orders?location_id=1").json()]
    assert ids == [second["id"], first_id]
    assert _a1(client.get(f"/api/refills/orders/{first_id}").json())["fill_qty"] == 15


def test_history_never_batch_rewritten(client):
    id1 = client.get("/api/refills/orders?location_id=1").json()[0]["id"]
    snap1 = client.get(f"/api/refills/orders/{id1}").json()
    id2 = client.post("/api/refills/run?location_id=1").json()["id"]
    snap2 = client.get(f"/api/refills/orders/{id2}").json()

    # 改所有货道的库存/在途/容量
    for l in client.get("/api/lanes?location_id=1").json():
        client.patch(f"/api/lanes/{l['id']}",
                     json={"stock": 0, "in_transit": 1, "capacity": l["capacity"] + 3})

    # 所有历史单逐行原样，汇总也不变
    for oid, snap in ((id1, snap1), (id2, snap2)):
        now = client.get(f"/api/refills/orders/{oid}").json()
        assert now["lines"] == snap["lines"]
        assert now["total_fill"] == snap["total_fill"]
        assert now["has_drift"] is False


def test_truncated_line_flagged_and_never_repaired(client):
    first_id = client.get("/api/refills/orders?location_id=1").json()[0]["id"]

    # 人为把库内 A1 行补量截短：15 → 1
    _dirty_order_lines(first_id, lambda d: [
        l.update(fill_qty=1) for l in d["lines"] if l["slot_no"] == "A1"])

    # 详情仍读出库内脏值 1，并单独标出「行已漂移」
    detail = client.get(f"/api/refills/orders/{first_id}").json()
    assert detail["has_drift"] is True
    assert _a1(detail)["fill_qty"] == 1
    assert _a1(detail)["drifted"] is True
    assert all(not l["drifted"] for l in detail["lines"] if l["slot_no"] != "A1")

    # 列表同样带漂移标记
    row = next(o for o in client.get("/api/refills/orders?location_id=1").json()
               if o["id"] == first_id)
    assert row["has_drift"] is True

    # 禁止不声张地写回修好：再读仍是脏值，库里仍是脏文本
    assert _a1(client.get(f"/api/refills/orders/{first_id}").json())["fill_qty"] == 1
    db = TestingSessionLocal()
    raw = json.loads(db.get(RefillOrder, first_id).lines_json)
    db.close()
    assert next(l for l in raw["lines"] if l["slot_no"] == "A1")["fill_qty"] == 1


def test_corrupt_json_served_raw_with_drift_flag(client):
    first_id = client.get("/api/refills/orders?location_id=1").json()[0]["id"]
    db = TestingSessionLocal()
    order = db.get(RefillOrder, first_id)
    order.lines_json = order.lines_json[:25]  # 截短成非法 JSON
    truncated = order.lines_json
    db.commit()
    db.close()

    detail = client.get(f"/api/refills/orders/{first_id}").json()
    assert detail["corrupt"] is True
    assert detail["has_drift"] is True
    assert detail["raw"] == truncated  # 脏文本原样交出
    row = next(o for o in client.get("/api/refills/orders?location_id=1").json()
               if o["id"] == first_id)
    assert row["has_drift"] is True and row["corrupt"] is True


def test_current_view_follows_lanes_and_never_persists(client):
    before = [o["id"] for o in client.get("/api/refills/orders?location_id=1").json()]
    a1_lane = next(l for l in client.get("/api/lanes?location_id=1").json()
                   if l["slot_no"] == "A1")
    client.patch(f"/api/lanes/{a1_lane['id']}", json={"stock": 18})

    cur = client.get("/api/refills/current?location_id=1").json()
    assert cur["live"] is True and cur["id"] is None
    assert _a1(cur)["fill_qty"] == 2  # 20-18 现算
    # 现算不落库
    assert [o["id"] for o in client.get("/api/refills/orders?location_id=1").json()] == before


def test_get_endpoints_have_no_side_effects(client):
    count = lambda: len(client.get("/api/refills/orders?location_id=1").json())
    assert count() == 1
    client.get("/api/refills/latest?location_id=1")
    client.get("/api/refills/summary?location_id=1")
    client.get("/api/refills/full?location_id=1")
    client.get("/api/refills/current?location_id=1")
    assert count() == 1  # 任何 GET 都不得生成单

    new = client.post("/api/refills/run?location_id=1").json()
    assert client.get("/api/refills/latest?location_id=1").json()["id"] == new["id"]


def test_latest_empty_state_does_not_generate(client):
    db = TestingSessionLocal()
    db.query(RefillOrder).delete()
    db.commit()
    db.close()
    latest = client.get("/api/refills/latest?location_id=1").json()
    assert latest["id"] is None and latest["empty"] is True
    assert client.get("/api/refills/orders?location_id=1").json() == []  # 未被偷偷生成
