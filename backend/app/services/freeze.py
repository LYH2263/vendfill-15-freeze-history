"""历史补货单的冻结与漂移检测。

世代规则：
- 一次成功生成即冻结：逐行补量/状态连同当时的容量、库存、在途一起快照，
  之后货道库存、在途、容量如何变化都不回写历史单。
- 行级签名单独存一份。读历史单时拿「库内当前行文本」重新签名比对：
  一致=冻结原貌；不一致=该行被截短/改脏，原样读出脏文本并标注「行已漂移」，
  绝不静默写回修复。
"""
from __future__ import annotations

import hashlib
import json

# 参与签名的字段顺序固定；缺字段 / 改值 / 截短都会改变签名。
_SIG_FIELDS = (
    "lane_id", "slot_no", "sku_name", "capacity", "stock",
    "in_transit", "gap", "fill_qty", "status",
)
SIG_VERSION = "v1"


def _canonical(line: dict) -> str:
    return json.dumps(
        [line.get(k) for k in _SIG_FIELDS],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def line_signature(line: dict) -> str:
    return f"{SIG_VERSION}:{_hash(_canonical(line))}"


def build_frozen(lines: list[dict]) -> tuple[str, str]:
    """把生成当时的行列表冻结为 (lines_json, line_sigs_json)。

    入参即生成时刻的快照（FillLine 转出的 dict），不重新现算。
    """
    rows = [dict(l) for l in lines]
    sigs: dict[str, str] = {}
    for l in rows:
        sigs[str(l.get("lane_id"))] = line_signature(l)
    envelope = {
        "sig_version": SIG_VERSION,
        "line_sigs": sigs,
    }
    return json.dumps(rows, ensure_ascii=False), json.dumps(envelope, ensure_ascii=False)


def _safe_loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def read_frozen(lines_text: str | None, sigs_text: str | None) -> dict:
    """读取历史单。返回的行内容永远以库内文本为准（含脏文本），另附漂移标注。

    返回：
      lines:          库内解析出的行（解析失败也不替换成现算值，给 [] 并标整体漂移）
      drift:          是否有任意漂移
      lines_drift:    {lane_id(str): 原因} 被改脏/截短的行
      missing_lines:  签名里有、行里没了的 lane_id
      extra_lines:    行里有、签名里没有的 lane_id
      lines_corrupt:  库内行 JSON 整体无法解析
    """
    raw_lines = _safe_loads(lines_text, None)
    # 兼容改造前落库的 envelope（{"lines": [...], ...}）：取出其中的行
    if isinstance(raw_lines, dict) and isinstance(raw_lines.get("lines"), list):
        raw_lines = raw_lines["lines"]
    lines_corrupt = not isinstance(raw_lines, list)
    lines: list[dict] = [] if lines_corrupt else [l for l in raw_lines if isinstance(l, dict)]

    sig_env = _safe_loads(sigs_text, {})
    if not isinstance(sig_env, dict):
        sig_env = {}
    sigs = sig_env.get("line_sigs", {})
    if not isinstance(sigs, dict):
        sigs = {}
    has_sigs = bool(sigs)

    present: set[str] = {str(l.get("lane_id")) for l in lines}
    signed: set[str] = {str(k) for k in sigs.keys()}

    lines_drift: dict[str, str] = {}
    missing_lines: list[str] = []
    extra_lines: list[str] = []
    if has_sigs:
        for l in lines:
            key = str(l.get("lane_id"))
            expected = sigs.get(key)
            # 生成之后新增进来的行没有签名，单独归为 extra，不当作改脏
            if expected is None:
                continue
            if line_signature(l) != expected:
                lines_drift[key] = "行已漂移：库内行内容与生成时冻结签名不一致"
        missing_lines = sorted(signed - present)
        extra_lines = sorted(present - signed)

    drift = bool(lines_drift or missing_lines or extra_lines or lines_corrupt)
    return {
        "lines": lines,
        "raw_lines_text": lines_text if lines_corrupt else None,
        "drift": drift,
        "lines_drift": lines_drift,
        "missing_lines": missing_lines,
        "extra_lines": extra_lines,
        "lines_corrupt": lines_corrupt,
    }
