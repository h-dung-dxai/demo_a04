"""Thiết bị giả lập Modbus TCP (cổng 5020).

Holding register:
  0  CRAC-01 nhiệt độ gió cấp (°C × 10)   – giá trị đo, dao động quanh mục tiêu
  1  UPS-01 tải (% × 10)                  – giá trị đo, dao động quanh mục tiêu
  10 mục tiêu nhiệt độ  (ghi bằng set_value.py)
  11 mục tiêu tải UPS   (ghi bằng set_value.py)
"""
import asyncio
import random

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartAsyncTcpServer

HR = 3  # function code holding register
store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0] * 20))
context = ModbusServerContext(slaves=store, single=True)
store.setValues(HR, 10, [235, 420])  # 23.5 °C, 42.0 %


async def drift():
    while True:
        temp, load = store.getValues(HR, 10, 2)
        store.setValues(HR, 0, [max(0, temp + random.randint(-3, 3)), max(0, load + random.randint(-5, 5))])
        await asyncio.sleep(1)


async def main():
    asyncio.create_task(drift())
    print("Simulator Modbus TCP đang chạy ở :5020", flush=True)
    await StartAsyncTcpServer(context=context, address=("0.0.0.0", 5020))


asyncio.run(main())
