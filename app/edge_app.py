"""Dịch vụ edge: ghi dữ liệu vào TimescaleDB tại chỗ + rule engine cảnh báo.

Nghe cả 2 broker (mqtt-a, mqtt-b) nên khi một edge node chết vẫn nhận dữ liệu từ node còn lại.
Cảnh báo được đánh giá ngay tại edge (không cần WAN), ghi DB và publish lên topic alerts
để bridge mang lên cloud (khi có WAN).
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from common import db_connect

SITE = os.environ.get("SITE", "site01")
BROKERS = os.environ["BROKERS"].split(",")
RULES = json.load(open(os.path.join(os.path.dirname(__file__), "rules.json")))
OPS = {">": lambda a, b: a > b, "<": lambda a, b: a < b}
RED, GREEN, RESET = "\033[1;31m", "\033[1;32m", "\033[0m"

db = db_connect(os.environ["EDGE_DB"])
db_lock = threading.Lock()  # psycopg connection dùng chung giữa các thread MQTT
state_lock = threading.RLock()

db.execute("""CREATE TABLE IF NOT EXISTS readings (
  site text, point text, ts timestamptz, value double precision, src text,
  PRIMARY KEY (site, point, ts))""")
db.execute("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE)")
db.execute("""CREATE TABLE IF NOT EXISTS alerts (
  id uuid PRIMARY KEY, site text, rule text, point text, severity text, message text,
  value double precision, raised_at timestamptz, cleared_at timestamptz, latency_s double precision)""")

last_seen = {}   # point -> thời điểm nhận gần nhất
active = {}      # rule key -> alert đang bật
clients = []


def sql(q, args=()):
    with db_lock:
        db.execute(q, args)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def save(a):
    sql("""INSERT INTO alerts (id, site, rule, point, severity, message, value, raised_at, cleared_at, latency_s)
           VALUES (%(id)s, %(site)s, %(rule)s, %(point)s, %(severity)s, %(message)s, %(value)s,
                   %(raised_at)s, %(cleared_at)s, %(latency_s)s)
           ON CONFLICT (id) DO UPDATE SET cleared_at = EXCLUDED.cleared_at""", a)
    for c in clients:  # gửi qua mọi broker còn sống; cloud khử trùng theo id
        if c.is_connected():
            c.publish(f"dcim/{SITE}/alerts", json.dumps(a), qos=1)


def set_alert(key, on, rule, point, value, measured_ts):
    with state_lock:
        now = time.time()
        if on and key not in active:
            a = {"id": str(uuid.uuid4()), "site": SITE, "rule": key, "point": point,
                 "severity": rule["severity"], "message": rule["message"], "value": value,
                 "raised_at": iso(now), "cleared_at": None,
                 "latency_s": round(now - measured_ts, 2) if measured_ts else None}
            active[key] = a
            lat = f" | {a['latency_s']}s kể từ lần đo" if measured_ts else ""
            print(f"{RED}🚨 [{a['severity']}] {a['message']} | {point}={"—" if value is None else f"{value:g}"}{lat} | CÒI + ĐÈN BẬT{RESET}", flush=True)
            save(a)
        elif not on and key in active:
            a = active.pop(key)
            a["cleared_at"] = iso(now)
            print(f"{GREEN}✅ Hết cảnh báo: {a['message']} | {point}{RESET}", flush=True)
            save(a)


def on_message(client, userdata, msg):
    d = json.loads(msg.payload)
    device = d["tags"].get("name") or d["name"]
    ts = d["timestamp"]
    for field, value in d["fields"].items():
        point = f"{device}.{field}"
        sql("""INSERT INTO readings (site, point, ts, value, src) VALUES (%s, %s, to_timestamp(%s), %s, %s)
               ON CONFLICT DO NOTHING""", (SITE, point, ts, value, d["tags"].get("host")))
        last_seen[point] = time.time()
        for r in RULES["thresholds"]:
            if r["point"] == point:
                set_alert(r["id"], OPS[r["op"]](value, r["value"]), r, point, value, ts)


def watchdog():
    """Cảnh báo 'mất liên lạc' khi một điểm đo không có dữ liệu quá stale_seconds."""
    rule = {"severity": "CRITICAL", "message": "Mất liên lạc thiết bị"}
    while True:
        now = time.time()
        for point, t in list(last_seen.items()):
            set_alert(f"stale:{point}", now - t > RULES["stale_seconds"], rule, point, None, None)
        time.sleep(1)


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Đã kết nối broker {userdata}", flush=True)
    client.subscribe("dcim/+/tm/#", qos=1)
    open("/tmp/ready", "w").close()


def on_disconnect(client, userdata, flags, reason_code, properties):
    print(f"Mất kết nối broker {userdata} – vẫn nhận dữ liệu qua broker còn lại", flush=True)


for i, host in enumerate(BROKERS):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"edge-app-{i}", userdata=host,
                    clean_session=False)  # broker giữ tin nhắn QoS1 nếu edge-app rớt kết nối ngắn
    c.on_connect, c.on_message, c.on_disconnect = on_connect, on_message, on_disconnect
    c.reconnect_delay_set(1, 2)
    c.connect_async(host, 1883, keepalive=5)
    c.loop_start()
    clients.append(c)

threading.Thread(target=watchdog, daemon=True).start()
print(f"edge-app ({SITE}) đang chạy – broker: {BROKERS}", flush=True)
while True:
    time.sleep(3600)
