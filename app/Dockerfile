FROM python:3.12-slim
RUN pip install --no-cache-dir pymodbus==3.6.9 paho-mqtt==2.1.0 "psycopg[binary]==3.2.3"
WORKDIR /app
COPY . /app
