"""Chạy simulator của modbus-lab trong mạng OT của demo, ở đúng địa chỉ thật của site.

Point Map ghi địa chỉ thật (gateway điện 10.20.0.21, BESS 10.20.0.30, UPS 10.20.0.40, CRAH 10.20.0.50).
Container sim gắn thêm từng IP đó vào card mạng (cần NET_ADMIN), rồi chạy sim.py --env site.
Telegraf và collector BACnet kết nối đúng các địa chỉ như ở site thật, không cần ánh xạ địa chỉ.
"""
import ipaddress
import os
import subprocess
import sys

from point_map import DEFAULT_PATH, SITE_ENV, is_rtu, load_or_exit

IFACE = "eth0"

cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
own = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", IFACE],
                     capture_output=True, text=True, check=True).stdout.split()[3]
net = ipaddress.ip_interface(own).network
hosts = sorted({d["host"] for d in cfg["devices"] if not is_rtu(d)}, key=ipaddress.ip_address)
for h in hosts:
    if ipaddress.ip_address(h) not in net:
        sys.exit(f"{h} trong Point Map không thuộc mạng edge {net} của docker-compose.yml: sửa subnet mạng edge")
    subprocess.run(["ip", "addr", "replace", f"{h}/32", "dev", IFACE], check=True)
print(f"Đã gắn địa chỉ thiết bị {', '.join(hosts)} vào {IFACE} (mạng {net})", flush=True)

os.execvp(sys.executable, [sys.executable, "-u", "tools/simulator/sim.py", "--env", SITE_ENV,
                           "--auto", os.environ.get("SIM_AUTO", "2"), "--control-host", "0.0.0.0"])
