"""Đọc BACnet cho Telegraf (plugin inputs.execd) — Telegraf không có plugin đọc BACnet.

Telegraf chạy script này và giữ nó chạy suốt. Mỗi chu kỳ thu thập, Telegraf gửi một dòng vào stdin;
script đọc mọi điểm BACnet trong Point Map (dùng lại bacnet_io của modbus-lab) và in ra line protocol.
Gửi MQTT, đệm khi broker rớt, gắn tag host đều do Telegraf lo, như với Modbus và SNMP.

Thời điểm đo làm tròn theo chu kỳ (giống round_interval của Telegraf), nên dữ liệu từ 2 edge node
có cùng timestamp và được khử trùng bằng khóa (site, point, ts).

Biến môi trường: BACNET_CLIENT — địa chỉ của edge node trên mạng BACnet/IP (IP/mặt nạ:cổng).
"""
import os
import sys
import time

out, sys.stdout = sys.stdout, sys.stderr   # stdout chỉ dành cho số liệu; mọi print khác thành log của Telegraf
# Telegraf ghi stderr của script vào log; tiền tố "I! " / "E! " chọn mức log (không có tiền tố = lỗi)

from bacnet_io import read_bacnet  # noqa: E402
from modbus_io import ReadError  # noqa: E402
from point_map import DEFAULT_PATH, SITE_ENV, load_or_exit  # noqa: E402

INTERVAL = 2   # giây, khớp [agent] interval trong telegraf/telegraf.conf

cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
site = cfg["site"]
devices = [d for d in cfg["devices"] if d.get("protocol") == "bacnet"]
for d in devices:
    d["bacnet_client"] = os.environ["BACNET_CLIENT"]   # mỗi edge node một địa chỉ riêng trên mạng BACnet/IP
print(f"I! BACnet qua {os.environ['BACNET_CLIENT']}: {', '.join(f'{d['name']} {d['host']}' for d in devices)}")

failing: set[str] = set()   # điểm đang đọc lỗi, để chỉ ghi log khi trạng thái đổi
for _ in sys.stdin:         # mỗi dòng = một chu kỳ thu thập của Telegraf
    ts = round(time.time() / INTERVAL) * INTERVAL
    for d in devices:
        fields = []
        for p in d["points"]:
            key = f"{d['name']}.{p['name']}"
            try:
                fields.append(f"{p['name']}={float(read_bacnet(d, p))}")
                if key in failing:
                    failing.discard(key)
                    print(f"I! Đọc lại được {key}")
            except Exception as e:
                if key not in failing:
                    failing.add(key)
                    print(f"E! Không đọc được {key}: {e}")
                if isinstance(e, ReadError):   # thiết bị không trả lời: bỏ các điểm còn lại của lượt này
                    break
        if fields:
            out.write(f"bacnet,site={site},device={d['name']} {','.join(fields)} {ts * 10**9}\n")
    out.flush()
