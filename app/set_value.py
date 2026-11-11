"""Đổi giá trị mục tiêu của thiết bị giả lập.  python set_value.py temp 30 | load 85"""
import sys

from pymodbus.client import ModbusTcpClient

REG = {"temp": 10, "load": 11}
kind, value = sys.argv[1], float(sys.argv[2])
c = ModbusTcpClient("sim", port=5020)
c.connect()
c.write_register(REG[kind], int(value * 10), slave=1)
c.close()
print(f"Đã đặt {kind} = {value}")
