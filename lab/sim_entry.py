"""Chạy simulator của modbus-lab trong mạng OT của demo, ở đúng địa chỉ thật của site.

Point Map ghi địa chỉ thật (gateway điện 10.20.0.21, BESS 10.20.0.30, UPS 10.20.0.40, CRAH 10.20.0.50).
Container sim gắn thêm từng IP đó vào card mạng (cần NET_ADMIN), rồi chạy sim.py --env site.
Telegraf và collector BACnet kết nối đúng các địa chỉ như ở site thật, không cần ánh xạ địa chỉ.

Bus RS-485 (thiết bị Modbus RTU) nằm sau bộ chuyển serial ↔ Ethernet: SERIAL_TCP="/dev/ttyUSB0=10.20.0.60:7000"
(nhiều bus cách nhau dấu phẩy). Simulator mở bus đó qua TCP (RTU over TCP), nên Telegraf ở container khác
và collector trên máy host đều đọc được — cổng serial ảo trong container thì không ai ngoài container mở được.
"""
import ipaddress
import os
import subprocess
import sys

from point_map import DEFAULT_PATH, SITE_ENV, is_rtu, load_or_exit

IFACE = "eth0"

cfg = load_or_exit(DEFAULT_PATH, SITE_ENV)
serial_tcp = [m for m in os.environ.get("SERIAL_TCP", "").split(",") if m]   # cổng=host:port của từng bus
own = subprocess.run(["ip", "-o", "-4", "addr", "show", "dev", IFACE],
                     capture_output=True, text=True, check=True).stdout.split()[3]
net = ipaddress.ip_interface(own).network
hosts = sorted({d["host"] for d in cfg["devices"] if not is_rtu(d)}
               | {m.split("=", 1)[1].rsplit(":", 1)[0] for m in serial_tcp}, key=ipaddress.ip_address)
for h in hosts:
    if ipaddress.ip_address(h) not in net:
        sys.exit(f"{h} trong Point Map không thuộc mạng edge {net} của docker-compose.yml: sửa subnet mạng edge")
    subprocess.run(["ip", "addr", "replace", f"{h}/32", "dev", IFACE], check=True)
print(f"Đã gắn địa chỉ thiết bị {', '.join(hosts)} vào {IFACE} (mạng {net})", flush=True)

os.execvp(sys.executable, [sys.executable, "-u", "tools/simulator/sim.py", "--env", SITE_ENV,
                           "--auto", os.environ.get("SIM_AUTO", "2"), "--control-host", "0.0.0.0",
                           *[a for m in serial_tcp for a in ("--serial-tcp", m)]])
