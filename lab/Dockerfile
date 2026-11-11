# Image chạy code của modbus-lab: simulator thiết bị, Point Map, và Telegraf của edge node
# (Telegraf chạy script đọc BACnet bằng Python, nên cần chung image với thư viện modbus-lab).
# Chỉ cài thư viện; mã nguồn modbus-lab được mount vào /lab lúc chạy (docker-compose.yml),
# nên sửa Point Map chỉ cần chạy lại demo, không phải build lại image.
FROM python:3.12-slim
# iproute2: sim_entry.py gắn IP thật của từng thiết bị vào card mạng của container sim
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
# Thư viện đúng phiên bản modbus-lab ghim (bỏ pytest)
COPY --from=modbus-lab requirements.txt /tmp/requirements.txt
RUN grep -v '^pytest' /tmp/requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt
# Telegraf là một file chạy Go độc lập: lấy nguyên từ image chính thức
COPY --from=telegraf:1.32 /usr/bin/telegraf /usr/bin/telegraf
# Giữ khớp PYTHONPATH trong Makefile của modbus-lab (các module import nhau theo tên ngắn)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/lab/tools/codec:/lab/tools/simulator:/lab/tools/dashboard:/lab/edge/write-service:/lab/edge/point-map:/lab/edge/modbus:/lab/edge/snmp:/lab/edge/collectors/telegraf:/lab/edge/collectors/bacnet:/lab/i18n
WORKDIR /lab
COPY *.py /demo/
