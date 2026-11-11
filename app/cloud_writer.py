"""Phía cloud: nhận dữ liệu và cảnh báo từ các site, ghi vào DB trung tâm.

Khóa (site, point, ts) + ON CONFLICT DO NOTHING: dữ liệu đến 2 lần (từ 2 edge node,
hoặc gửi lại sau khi mất WAN) không bị trùng. received_at cho biết bản ghi nào được gửi bù.
"""
import json
import os
import time

import paho.mqtt.client as mqtt

from common import db_connect

db = db_connect(os.environ["CLOUD_DB"])
db.execute("""CREATE TABLE IF NOT EXISTS readings (
  site text, point text, ts timestamptz, value double precision, src text,
  received_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, point, ts))""")
db.execute("""CREATE TABLE IF NOT EXISTS alerts (
  id uuid PRIMARY KEY, site text, rule text, point text, severity text, message text,
  value double precision, raised_at timestamptz, cleared_at timestamptz, latency_s double precision,
  received_at timestamptz NOT NULL DEFAULT now())""")


def on_message(client, userdata, msg):
    _, site, kind, *_ = msg.topic.split("/")
    d = json.loads(msg.payload)
    if kind == "tm":
        device = d["tags"]["device"]
        for field, value in d["fields"].items():
            db.execute("""INSERT INTO readings (site, point, ts, value, src)
                          VALUES (%s, %s, to_timestamp(%s), %s, %s) ON CONFLICT DO NOTHING""",
                       (site, f"{device}.{field}", d["timestamp"], value, d["tags"].get("host")))
    elif kind == "alerts":
        db.execute("""INSERT INTO alerts (id, site, rule, point, severity, message, value, raised_at, cleared_at, latency_s)
                      VALUES (%(id)s, %(site)s, %(rule)s, %(point)s, %(severity)s, %(message)s, %(value)s,
                              %(raised_at)s, %(cleared_at)s, %(latency_s)s)
                      ON CONFLICT (id) DO UPDATE SET cleared_at = COALESCE(EXCLUDED.cleared_at, alerts.cleared_at)""", d)


def on_connect(client, userdata, flags, reason_code, properties):
    print("cloud-writer đã kết nối mqtt-cloud", flush=True)
    client.subscribe("dcim/#", qos=1)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="cloud-writer", clean_session=False)
c.on_connect, c.on_message = on_connect, on_message
while True:
    try:
        c.connect("mqtt-cloud", 1883, keepalive=10)
        break
    except OSError:
        print("chờ mqtt-cloud...", flush=True)
        time.sleep(2)
c.loop_forever()
