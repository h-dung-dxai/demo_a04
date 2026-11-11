import time

import psycopg


def db_connect(url):
    """Kết nối Postgres, chờ tối đa ~2 phút khi DB đang khởi động."""
    for _ in range(60):
        try:
            return psycopg.connect(url, autocommit=True, options="-c timezone=Asia/Ho_Chi_Minh")
        except psycopg.OperationalError as e:
            print("chờ DB...", str(e).splitlines()[0], flush=True)
            time.sleep(2)
    raise SystemExit(f"Không kết nối được DB: {url}")
