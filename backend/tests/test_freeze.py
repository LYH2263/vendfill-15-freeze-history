from app.services.freeze import build_frozen, read_frozen


def _line(lane_id=1, fill=15):
    return {"lane_id": lane_id, "slot_no": "A1", "sku_name": "水", "capacity": 20,
            "stock": 5, "in_transit": 0, "gap": 15, "fill_qty": fill, "status": "need_fill"}


def test_clean_freeze_has_no_drift():
    text, sigs = build_frozen([_line()])
    fr = read_frozen(text, sigs)
    assert fr["drift"] is False
    assert fr["lines"][0]["fill_qty"] == 15
    assert fr["lines_corrupt"] is False


def test_value_tamper_marks_line_drift_but_keeps_dirty_text():
    text, sigs = build_frozen([_line(fill=15)])
    dirty = text.replace('"fill_qty": 15', '"fill_qty": 9')
    assert dirty != text
    fr = read_frozen(dirty, sigs)
    assert fr["drift"] is True
    assert fr["lines"][0]["fill_qty"] == 9          # 跟库内脏文本
    assert "1" in fr["lines_drift"]
    # 不写回：read_frozen 纯函数，返回脏文本不动
    assert fr["lines"][0]["fill_qty"] != 15


def test_truncated_json_is_corrupt_and_raw_returned():
    text, sigs = build_frozen([_line()])
    truncated = text[: len(text) - 12]
    fr = read_frozen(truncated, sigs)
    assert fr["lines_corrupt"] is True
    assert fr["drift"] is True
    assert fr["raw_lines_text"] == truncated


def test_missing_line_detected():
    text, sigs = build_frozen([_line(1), _line(2, fill=3)])
    keep_one = text.split('{"lane_id": 2')[0].rstrip().rstrip(",") + "]"
    import json as _json
    parsed = _json.loads(keep_one)
    assert len(parsed) == 1
    fr = read_frozen(keep_one, sigs)
    assert fr["missing_lines"] == ["2"]
    assert fr["drift"] is True


def test_legacy_unsigned_rows_not_flagged():
    # 改造前老数据没有签名：正常行不应误报漂移
    text, sigs = build_frozen([_line()])
    fr = read_frozen(text, "{}")
    assert fr["drift"] is False
