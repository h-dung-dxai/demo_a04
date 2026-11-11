"""Sinh cấu hình edge từ Point Map của modbus-lab (Point Map là nguồn dữ liệu duy nhất).

  python gen_edge_config.py <thư mục ra> <dashboard gốc>
    devices.conf        inputs Telegraf: Modbus TCP, Modbus RTU qua TCP và SNMP (generate.py của modbus-lab,
                        môi trường site) + BACnet qua inputs.execd (bacnet_execd.py)
    rules.json          tên site + luật cảnh báo (mục alerts của Point Map) cho rule engine edge-app
    grafana/a04.json    dashboard gốc + thẻ từng thiết bị (edge và cloud), mọi điểm đo kèm đơn vị và ngưỡng
    grafana/a04-ja.json bản tiếng Nhật: dịch theo translations.ja.json cạnh dashboard gốc; tên thiết bị, điểm đo,
                        nội dung cảnh báo lấy nhãn ja trong Point Map

Modbus RTU: bus RS-485 nằm sau bộ chuyển serial ↔ Ethernet (SERIAL_TCP, cùng giá trị với service sim),
Telegraf đọc bằng RTU over TCP. Bus không có trong SERIAL_TCP thì bỏ thiết bị trên bus đó (không mở được).
BACnet: Telegraf không có plugin, nên Telegraf chạy bacnet_execd.py (inputs.execd) để đọc.
"""
import json
import os
import sys
from pathlib import Path

from generate import generate
from point_map import DEFAULT_PATH, SITE_ENV, SOCKET, is_rtu, load_or_exit, serial_over_tcp

STALE_SECONDS = 10   # không có dữ liệu quá chừng này giây -> cảnh báo mất liên lạc thiết bị

out = Path(sys.argv[1])
cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
errors = serial_over_tcp(cfg, dict(m.split("=", 1) for m in os.environ.get("SERIAL_TCP", "").split(",") if m))
if errors:
    sys.exit("SERIAL_TCP: " + "; ".join(errors))
rtu = [d["name"] for d in cfg["devices"] if is_rtu(d) and not d["serial"]["port"].startswith(SOCKET)]
cfg["devices"] = [d for d in cfg["devices"] if d["name"] not in rtu]
cfg["alerts"] = [a for a in cfg.get("alerts", []) if a["point"].split(".")[0] not in rtu]
# chỉ lấy inputs: [agent] và outputs đã có trong telegraf/telegraf.conf (trùng [agent] thì Telegraf báo lỗi)
telegraf = "\n\n".join(b for b in generate(cfg).split("\n\n")
                       if not b.lstrip().startswith(("[agent]", "[[outputs.")))
bacnet = [d["name"] for d in cfg["devices"] if d.get("protocol") == "bacnet"]
if bacnet:
    telegraf += "\n".join(["", f"# BACnet ({', '.join(bacnet)}): Telegraf chạy script đọc theo Point Map, nhận line protocol",
                           "[[inputs.execd]]",
                           '  command = ["python", "/demo/bacnet_execd.py"]',
                           '  signal = "STDIN"',
                           '  restart_delay = "2s"',
                           '  data_format = "influx"', ""])
(out / "devices.conf").write_text(telegraf, encoding="utf-8")


def rule(a: dict) -> dict:
    kind = "above" if "above" in a else "below"
    return {"id": f"{a['point']}:{kind}", "point": a["point"], "op": ">" if kind == "above" else "<",
            "value": a[kind], "severity": "CRITICAL", "message": a["message"]["vi"]}


rules = {"site": cfg["site"], "stale_seconds": STALE_SECONDS, "thresholds": [rule(a) for a in cfg.get("alerts", [])]}
(out / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Dashboard: tiếng Việt (a04) và tiếng Nhật (a04-ja), thẻ thiết bị ----------
UNITS = {"V": "volt", "A": "amp", "W": "watt", "°C": "celsius", "%": "percent", "": "none"}
DEVICE_SECTION_Y = 31   # thẻ thiết bị chèn vào đây; panel gốc từ dòng này trở xuống bị đẩy xuống dưới
CARD_H = 4
JA = json.loads(Path(sys.argv[2]).with_name("translations.ja.json").read_text(encoding="utf-8"))
TEXT = {"vi": {"device": "thiết bị", "via_tcp": "qua TCP", "threshold": "ngưỡng",
               "row": "Thiết bị theo Point Map – {devices} thiết bị, {points} điểm đo{skipped} · trái = edge, phải = cloud",
               "skipped": " (không đọc RS-485: {names})"},
        "ja": JA["cards"]}


def translate(obj, phrases: dict):
    """Thay mọi cụm tiếng Việt trong mọi chuỗi của dashboard; cụm dài thay trước để không cắt vụn cụm dài."""
    if isinstance(obj, dict):
        return {k: translate(v, phrases) for k, v in obj.items()}
    if isinstance(obj, list):
        return [translate(v, phrases) for v in obj]
    if isinstance(obj, str):
        for vi in sorted(phrases, key=len, reverse=True):
            obj = obj.replace(vi, phrases[vi])
    return obj


def where(d: dict, lang: str) -> str:
    t, proto = TEXT[lang], d.get("protocol", "modbus")
    if proto == "snmp":
        return f"SNMP {d['host']}"
    if proto == "bacnet":
        return f"BACnet/IP {d['host']} · instance {d['device_instance']}"
    if is_rtu(d):
        return (f"Modbus RTU {d['site_address'].removeprefix('rtu:')} {t['via_tcp']} "
                f"{d['serial']['port'].removeprefix(SOCKET)} · {t['device']} {d['device_id']}")
    return f"Modbus TCP {d['host']}:{d['port']} · {t['device']} {d['device_id']}"


def is_integer(p: dict) -> bool:
    """Điểm chỉ mang số nguyên (trạng thái, chế độ, lệnh): hiện không có phần thập phân."""
    whole_type = p.get("type") in ("int16", "uint16", "int32", "uint32", "integer") and p.get("scale", 1) == 1
    return whole_type or "allowed" in p or p.get("object", "").startswith("binary")


def card(pid: int, d: dict, side: str, x: int, y: int, lang: str) -> dict:
    ds = {"type": "grafana-postgresql-datasource", "uid": side}
    # một dòng, mỗi điểm một cột theo thứ tự Point Map; quá STALE_SECONDS không có dữ liệu thì trống ("—")
    sql = "SELECT " + ", ".join(
        f"(SELECT value FROM readings WHERE site = '{cfg['site']}' AND point = '{d['name']}.{p['name']}' "
        f"AND ts > now() - interval '{STALE_SECONDS} seconds' ORDER BY ts DESC LIMIT 1) AS \"{p['name']}\""
        for p in d["points"])
    overrides = []
    for p in d["points"]:
        name, props = p["label"][lang], [{"id": "unit", "value": UNITS.get(p.get("unit", ""), f"suffix:{p['unit']}")}]
        if is_integer(p):
            props.append({"id": "decimals", "value": 0})
        for r in rules["thresholds"]:   # điểm có luật cảnh báo: đỏ khi vượt ngưỡng, như rule engine
            if r["point"] == f"{d['name']}.{p['name']}":
                steps = ([{"color": "green", "value": None}, {"color": "red", "value": r["value"]}] if r["op"] == ">"
                         else [{"color": "red", "value": None}, {"color": "green", "value": r["value"]}])
                name += f" ({TEXT[lang]['threshold']} {r['op']} {r['value']:g})"
                props.append({"id": "thresholds", "value": {"mode": "absolute", "steps": steps}})
        props.append({"id": "displayName", "value": name})
        overrides.append({"matcher": {"id": "byName", "options": p["name"]}, "properties": props})
    return {"id": pid, "type": "stat", "title": f"{d['label'][lang]} – {where(d, lang)}", "datasource": ds,
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


def ja_messages() -> str:
    """Bảng cảnh báo bản tiếng Nhật: DB lưu nội dung tiếng Việt, đổi sang message.ja của Point Map theo mã luật."""
    q = lambda s: s.replace("'", "''")
    whens = " ".join(f"WHEN rule = '{q(rule(a)['id'])}' THEN '{q(a['message']['ja'])}'" for a in cfg.get("alerts", []))
    return f"CASE {whens} WHEN rule LIKE 'stale:%' THEN '{q(JA['cards']['stale'])}' ELSE message END"


template = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
points = sum(len(d["points"]) for d in cfg["devices"])
(out / "grafana").mkdir(exist_ok=True)
for lang, uid in (("vi", "a04"), ("ja", "a04-ja")):
    dash = json.loads(json.dumps(template))
    if lang == "ja":
        dash = translate(dash, JA["dashboard"])
        for p in dash["panels"]:
            for t in p.get("targets", []):
                t["rawSql"] = t["rawSql"].replace('message AS "内容"', f'{ja_messages()} AS "内容"')
    dash["uid"] = uid
    for p in dash["panels"]:
        if p["gridPos"]["y"] >= DEVICE_SECTION_Y:
            p["gridPos"]["y"] += 1 + CARD_H * len(cfg["devices"])
    t = TEXT[lang]
    skipped = t["skipped"].format(names=", ".join(rtu)) if rtu else ""
    dash["panels"].append({"id": 100, "type": "row", "collapsed": False, "panels": [],
                           "gridPos": {"x": 0, "y": DEVICE_SECTION_Y, "w": 24, "h": 1},
                           "title": t["row"].format(devices=len(cfg["devices"]), points=points, skipped=skipped)})
    for i, d in enumerate(cfg["devices"]):
        y = DEVICE_SECTION_Y + 1 + CARD_H * i
        dash["panels"] += [card(101 + 2 * i, d, "edge", 0, y, lang), card(102 + 2 * i, d, "cloud", 12, y, lang)]
    (out / "grafana" / f"{uid}.json").write_text(json.dumps(dash, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"Point Map site {cfg['site']}: {len(cfg['devices'])} thiết bị, {points} điểm đo, "
      f"{len(rules['thresholds'])} luật cảnh báo{f'; bỏ qua thiết bị RS-485: {', '.join(rtu)}' if rtu else ''}")
for r in rules["thresholds"]:
    print(f"  {r['point']} {r['op']} {r['value']:g}  {r['message']}")
