"""验收：历史补货单冻结 / 分世代 / 行漂移。

必须在导入 app 之前指定 SQLite 临时库。
"""
import json
import os
import pathlib
import tempfile

_tmp = tempfile.mkdtemp(prefix="vendfill-test-")
_db_path = pathlib.Path(_tmp) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SEED_ON_EMPTY"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


def _line(doc, slot):
    hit = [l for l in doc["lines"] if l["slot_no"] == slot]
    assert hit, f"缺少货道 {slot}"
    return hit[0]


def test_freeze_generation_and_drift():
    with TestClient(app) as client:
        # ---- 种子已冻结第 1 代，记下 A1 补量 ----
        orders = client.get("/api/refills").json()
        assert len(orders) == 1
        gen1_id = orders[0]["id"]
        assert orders[0]["generation"] == 1
        assert orders[0]["frozen"] is True
        assert orders[0]["drift"] is False

        gen1 = client.get(f"/api/refills/{gen1_id}").json()
        a1_gen1 = _line(gen1, "A1")
        assert a1_gen1["fill_qty"] == 15          # 20 - 5 - 0
        assert a1_gen1["stock"] == 5
        assert a1_gen1["line_drift"] is False

        lanes = {l["slot_no"]: l for l in client.get("/api/lanes?location_id=1").json()}
        a1_id = lanes["A1"]["id"]

        # ---- 货道页把 A1 库存改大并保存 ----
        client.patch(f"/api/lanes/{a1_id}", json={"stock": 18}).raise_for_status()

        # 历史旧单：数字不变，仍显示生成当时的补量/库存/状态
        gen1_after = client.get(f"/api/refills/{gen1_id}").json()
        a1_old = _line(gen1_after, "A1")
        assert a1_old["fill_qty"] == 15
        assert a1_old["stock"] == 5
        assert a1_old["gap"] == 15
        assert gen1_after["drift"] is False

        # 现算视图跟随新货道
        cur = client.get("/api/refills/current").json()
        assert _line(cur, "A1")["gap"] == 2
        assert _line(cur, "A1")["fill_qty"] == 2
        assert cur["frozen"] is False

        # 现算接口不得落库
        client.get("/api/refills/view/full")
        client.get("/api/refills/view/summary")
        assert len(client.get("/api/refills").json()) == 1

        # ---- 再点生成：第 2 代反映新缺口，A1 补量变小 ----
        gen2 = client.post("/api/refills/run").json()
        assert gen2["generation"] == 2
        assert _line(gen2, "A1")["fill_qty"] == 2
        assert _line(gen2, "A1")["stock"] == 18

        # 两单并排可对：列表按世代倒序，旧单依旧 15
        rows = client.get("/api/refills").json()
        assert [r["generation"] for r in rows] == [2, 1]
        gen1_row = [r for r in rows if r["generation"] == 1][0]
        gen2_row = [r for r in rows if r["generation"] == 2][0]
        assert gen1_row["total_fill"] != gen2_row["total_fill"]
        assert _line(client.get(f"/api/refills/{gen1_id}").json(), "A1")["fill_qty"] == 15

        # latest 是最新一次生成的冻结单（纯读，不偷偷再生成）
        latest = client.get("/api/refills/latest").json()
        assert latest["id"] == gen2["id"]
        assert len(client.get("/api/refills").json()) == 2

        # ---- 人为截短旧单行文本（JSON 直接截断到不可解析）----
        db = SessionLocal()
        raw = db.execute(text("SELECT lines_json FROM refill_orders WHERE id=:i"),
                         {"i": gen1_id}).scalar_one()
        truncated = raw[: len(raw) - 40]
        assert not truncated.endswith("]")  # 确认已截断
        db.execute(text("UPDATE refill_orders SET lines_json=:t WHERE id=:i"),
                   {"t": truncated, "i": gen1_id})
        db.commit()
        db.close()

        d1 = client.get(f"/api/refills/{gen1_id}").json()
        assert d1["drift"] is True
        assert d1["lines_corrupt"] is True
        # 详情仍显示库内的脏文本，而不是现算覆盖
        assert d1["raw_lines_text"] == truncated
        # 列表也单独标出
        d1_row = [r for r in client.get("/api/refills").json() if r["id"] == gen1_id][0]
        assert d1_row["drift"] is True
        assert d1_row["lines_corrupt"] is True

        # 禁止不声张地写回修好：库内依旧是截短文本
        db = SessionLocal()
        still = db.execute(text("SELECT lines_json FROM refill_orders WHERE id=:i"),
                           {"i": gen1_id}).scalar_one()
        db.close()
        assert still == truncated

        # ---- 另一单做“可解析但改脏”：把第 2 代 A1 补量 2 改成 9 ----
        db = SessionLocal()
        raw2 = db.execute(text("SELECT lines_json FROM refill_orders WHERE id=:i"),
                          {"i": gen2["id"]}).scalar_one()
        data2 = json.loads(raw2)
        for l in data2:
            if l["slot_no"] == "A1":
                l["fill_qty"] = 9
        dirty2 = json.dumps(data2, ensure_ascii=False)
        db.execute(text("UPDATE refill_orders SET lines_json=:t WHERE id=:i"),
                   {"t": dirty2, "i": gen2["id"]})
        db.commit()
        db.close()

        d2 = client.get(f"/api/refills/{gen2['id']}").json()
        a1_dirty = _line(d2, "A1")
        assert a1_dirty["fill_qty"] == 9          # 读出跟库内脏文本
        assert a1_dirty["line_drift"] is True
        assert "漂移" in a1_dirty["line_drift_reason"]
        assert d2["drift"] is True
        assert str(a1_dirty["lane_id"]) in d2["lines_drift"]
        d2_row = [r for r in client.get("/api/refills").json() if r["id"] == gen2["id"]][0]
        assert d2_row["drift"] is True
        assert d2_row["drift_line_count"] >= 1

        # ---- 再次改库存：所有历史单都不得被批量改写 ----
        db = SessionLocal()
        before = dict(db.execute(
            text("SELECT id, lines_json FROM refill_orders")).all())
        db.close()
        client.patch(f"/api/lanes/{a1_id}", json={"stock": 1, "in_transit": 3, "capacity": 30})
        db = SessionLocal()
        after = dict(db.execute(
            text("SELECT id, lines_json FROM refill_orders")).all())
        db.close()
        assert before == after
