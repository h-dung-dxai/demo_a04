"""Sinh cấu hình edge từ Point Map của modbus-lab (Point Map là nguồn dữ liệu duy nhất).

  python gen_edge_config.py <thư mục ra> <dashboard gốc>
    devices.conf        inputs Telegraf cho Modbus TCP và SNMP (generate.py của modbus-lab, môi trường site)
    rules.json          tên site + luật cảnh báo (mục alerts của Point Map) cho rule engine edge-app
    grafana/a04.json    dashboard gốc + thẻ từng thiết bị (edge và cloud), mọi điểm đo kèm đơn vị và ngưỡng

Bỏ thiết bị Modbus RTU: bus RS-485 cắm USB vào đúng một server edge, container khác không mở được.
BACnet do bacnet_collector.py đọc (Telegraf không đọc BACnet).
"""
import json
import sys
from pathlib import Path

from generate import generate
from point_map import DEFAULT_PATH, SITE_ENV, is_rtu, load_or_exit

STALE_SECONDS = 10   # không có dữ liệu quá chừng này giây -> cảnh báo mất liên lạc thiết bị

out = Path(sys.argv[1])
cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
rtu = [d["name"] for d in cfg["devices"] if is_rtu(d)]
cfg["devices"] = [d for d in cfg["devices"] if not is_rtu(d)]
(out / "devices.conf").write_text(generate(cfg, inputs_only=True), encoding="utf-8")


def rule(a: dict) -> dict:
    kind = "above" if "above" in a else "below"
    return {"id": f"{a['point']}:{kind}", "point": a["point"], "op": ">" if kind == "above" else "<",
            "value": a[kind], "severity": "CRITICAL", "message": a["message"]["vi"]}


rules = {"site": cfg["site"], "stale_seconds": STALE_SECONDS, "thresholds": [rule(a) for a in cfg.get("alerts", [])]}
(out / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Dashboard: thẻ thiết bị ----------
UNITS = {"V": "volt", "A": "amp", "W": "watt", "°C": "celsius", "%": "percent", "": "none"}
DEVICE_SECTION_Y = 31   # thẻ thiết bị chèn vào đây; panel gốc từ dòng này trở xuống bị đẩy xuống dưới
CARD_H = 4


def where(d: dict) -> str:
    proto = d.get("protocol", "modbus")
    if proto == "snmp":
        return f"SNMP {d['host']}"
    if proto == "bacnet":
        return f"BACnet/IP {d['host']} · instance {d['device_instance']}"
    return f"Modbus TCP {d['host']}:{d['port']} · thiết bị {d['device_id']}"


def is_integer(p: dict) -> bool:
    """Điểm chỉ mang số nguyên (trạng thái, chế độ, lệnh): hiện không có phần thập phân."""
    whole_type = p.get("type") in ("int16", "uint16", "int32", "uint32", "integer") and p.get("scale", 1) == 1
    return whole_type or "allowed" in p or p.get("object", "").startswith("binary")


def card(pid: int, d: dict, side: str, x: int, y: int) -> dict:
    ds = {"type": "grafana-postgresql-datasource", "uid": side}
    # một dòng, mỗi điểm một cột theo thứ tự Point Map; quá STALE_SECONDS không có dữ liệu thì trống ("—")
    sql = "SELECT " + ", ".join(
        f"(SELECT value FROM readings WHERE site = '{cfg['site']}' AND point = '{d['name']}.{p['name']}' "
        f"AND ts > now() - interval '{STALE_SECONDS} seconds' ORDER BY ts DESC LIMIT 1) AS \"{p['name']}\""
        for p in d["points"])
    overrides = []
    for p in d["points"]:
        name, props = p["label"]["vi"], [{"id": "unit", "value": UNITS.get(p.get("unit", ""), f"suffix:{p['unit']}")}]
        if is_integer(p):
            props.append({"id": "decimals", "value": 0})
        for r in rules["thresholds"]:   # điểm có luật cảnh báo: đỏ khi vượt ngưỡng, như rule engine
            if r["point"] == f"{d['name']}.{p['name']}":
                steps = ([{"color": "green", "value": None}, {"color": "red", "value": r["value"]}] if r["op"] == ">"
                         else [{"color": "red", "value": None}, {"color": "green", "value": r["value"]}])
                name += f" (ngưỡng {r['op']} {r['value']:g})"
                props.append({"id": "thresholds", "value": {"mode": "absolute", "steps": steps}})
        props.append({"id": "displayName", "value": name})
        overrides.append({"matcher": {"id": "byName", "options": p["name"]}, "properties": props})
    return {"id": pid, "type": "stat", "title": f"{d['label']['vi']} – {where(d)}", "datasource": ds,
            "gridPos": {"x": x, "y": y, "w": 12, "h": CARD_H},
            "targets": [{"refId": "A", "datasource": ds, "rawSql": sql, "format": "table",
                         "rawQuery": True, "editorMode": "code"}],
            "options": {"colorMode": "value", "graphMode": "none", "textMode": "value_and_name",
                        "justifyMode": "auto", "orientation": "vertical", "wideLayout": True,
                        "text": {"titleSize": 12, "valueSize": 24},
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            "fieldConfig": {"defaults": {"decimals": 1, "noValue": "—", "color": {"mode": "thresholds"},
                                         "thresholds": {"mode": "absolute", "steps": [{"color": "text", "value": None}]}},
                            "overrides": overrides}}


dash = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
height = 1 + CARD_H * len(cfg["devices"])
for p in dash["panels"]:
    if p["gridPos"]["y"] >= DEVICE_SECTION_Y:
        p["gridPos"]["y"] += height
points = sum(len(d["points"]) for d in cfg["devices"])
dash["panels"].append({"id": 100, "type": "row", "collapsed": False, "panels": [],
                       "gridPos": {"x": 0, "y": DEVICE_SECTION_Y, "w": 24, "h": 1},
                       "title": f"Thiết bị theo Point Map – {len(cfg['devices'])} thiết bị, {points} điểm đo"
                                f"{f' (không đọc RS-485: {', '.join(rtu)})' if rtu else ''} · trái = edge, phải = cloud"})
for i, d in enumerate(cfg["devices"]):
    y = DEVICE_SECTION_Y + 1 + CARD_H * i
    dash["panels"] += [card(101 + 2 * i, d, "edge", 0, y), card(102 + 2 * i, d, "cloud", 12, y)]
(out / "grafana").mkdir(exist_ok=True)
(out / "grafana" / "a04.json").write_text(json.dumps(dash, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"Point Map site {cfg['site']}: {len(cfg['devices'])} thiết bị, {points} điểm đo, "
      f"{len(rules['thresholds'])} luật cảnh báo{f'; bỏ qua thiết bị RS-485: {', '.join(rtu)}' if rtu else ''}")
for r in rules["thresholds"]:
    print(f"  {r['point']} {r['op']} {r['value']:g}  {r['message']}")
