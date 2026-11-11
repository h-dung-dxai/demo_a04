# Image chạy code của modbus-lab: simulator thiết bị, Point Map, collector BACnet.
# Chỉ cài thư viện; mã nguồn modbus-lab được mount vào /lab lúc chạy (docker-compose.yml),
# nên sửa Point Map chỉ cần chạy lại demo, không phải build lại image.
FROM python:3.12-slim
# iproute2: sim_entry.py gắn IP thật của từng thiết bị vào card mạng của container sim
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
# Thư viện đúng phiên bản modbus-lab ghim (bỏ pytest), thêm paho-mqtt cho collector BACnet
COPY --from=modbus-lab requirements.txt /tmp/requirements.txt
RUN grep -v '^pytest' /tmp/requirements.txt > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt paho-mqtt==2.1.0
# Giữ khớp PYTHONPATH trong Makefile của modbus-lab (các module import nhau theo tên ngắn)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/lab/tools/codec:/lab/tools/simulator:/lab/tools/dashboard:/lab/edge/write-service:/lab/edge/point-map:/lab/edge/modbus:/lab/edge/snmp:/lab/edge/collectors/telegraf:/lab/edge/collectors/bacnet:/lab/i18n
WORKDIR /lab
COPY *.py /demo/
