"""Collector BACnet tại edge node: đọc mọi điểm BACnet trong Point Map, gửi lên MQTT cục bộ như Telegraf.

Telegraf không đọc BACnet, nên mỗi edge node chạy thêm collector này (dùng lại bacnet_io của modbus-lab).
Bản tin cùng dạng JSON với Telegraf (name, tags, fields, timestamp) và cùng nhịp 2 giây làm tròn,
nên edge-app và cloud khử trùng dữ liệu từ 2 edge node giống hệt dữ liệu Telegraf.

Biến môi trường: EDGE_NAME, MQTT_HOST, BACNET_CLIENT (IP/mặt nạ:cổng của edge node trên mạng BACnet/IP).
"""
import json
import os
import time

import paho.mqtt.client as mqtt

from bacnet_io import read_bacnet
from modbus_io import ReadError
from point_map import DEFAULT_PATH, SITE_ENV, load_or_exit

INTERVAL = 2   # giây, khớp [agent] interval của Telegraf
EDGE = os.environ["EDGE_NAME"]

cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
site = cfg["site"]
devices = [d for d in cfg["devices"] if d.get("protocol") == "bacnet"]
for d in devices:
    d["bacnet_client"] = os.environ["BACNET_CLIENT"]   # mỗi edge node một địa chỉ riêng trên mạng BACnet/IP

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{EDGE}-bacnet")
client.reconnect_delay_set(1, 2)
client.connect_async(os.environ["MQTT_HOST"], 1883, keepalive=30)
client.loop_start()
print(f"Collector BACnet {EDGE} ({os.environ['BACNET_CLIENT']}): "
      f"{', '.join(f'{d['name']} {d['host']}' for d in devices)}", flush=True)

failing: set[str] = set()   # điểm đang đọc lỗi, để chỉ in khi trạng thái đổi
while True:
    ts = (int(time.time()) // INTERVAL + 1) * INTERVAL
    time.sleep(max(0.0, ts - time.time()))
    for d in devices:
        fields = {}
        for p in d["points"]:
            key = f"{d['name']}.{p['name']}"
            try:
                fields[p["name"]] = read_bacnet(d, p)
                if key in failing:
                    failing.discard(key)
                    print(f"Đọc lại được {key}", flush=True)
            except Exception as e:
                if key not in failing:
                    failing.add(key)
                    print(f"Không đọc được {key}: {e}", flush=True)
                if isinstance(e, ReadError):   # thiết bị không trả lời: bỏ các điểm còn lại của lượt này
                    break
        if fields:
            msg = {"name": "bacnet", "tags": {"site": site, "device": d["name"], "host": EDGE},
                   "fields": fields, "timestamp": ts}
            client.publish(f"dcim/{site}/tm/{d['name']}", json.dumps(msg), qos=1)
