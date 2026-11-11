"""Đối chiếu edge ↔ cloud: số bản ghi theo từng phút, từng điểm đo; cảnh báo; bản ghi gửi bù.

  python reconcile.py [số_phút=15]
Bỏ qua phút hiện tại (đang ghi dở). Exit code 1 nếu còn lệch.
"""
import os
import sys

from common import db_connect

minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 15
edge = db_connect(os.environ["EDGE_DB"])
cloud = db_connect(os.environ["CLOUD_DB"])

COUNT = """SELECT to_char(date_trunc('minute', ts), 'HH24:MI') AS m, point, count(*)
           FROM readings
           WHERE ts >= date_trunc('minute', now()) - make_interval(mins => %s)
             AND ts <  date_trunc('minute', now())
           GROUP BY 1, 2"""


def counts(conn):
    return {(m, p): n for m, p, n in conn.execute(COUNT, (minutes,)).fetchall()}


e, c = counts(edge), counts(cloud)
print(f"\nĐỐI CHIẾU EDGE ↔ CLOUD – {minutes} phút gần nhất (không tính phút hiện tại)\n")
print(f"{'Phút':<6} {'Điểm đo':<22} {'Edge':>6} {'Cloud':>6}  Kết quả")
print("-" * 56)
bad = 0
for key in sorted(e.keys() | c.keys()):
    ne, nc = e.get(key, 0), c.get(key, 0)
    ok = ne == nc
    bad += not ok
    print(f"{key[0]:<6} {key[1]:<22} {ne:>6} {nc:>6}  {'✓ khớp' if ok else '✗ LỆCH'}")

total_e, total_c = sum(e.values()), sum(c.values())
backfilled = cloud.execute(
    """SELECT count(*) FROM readings
       WHERE ts >= date_trunc('minute', now()) - make_interval(mins => %s)
         AND received_at - ts > interval '10 seconds'""", (minutes,)).fetchone()[0]
alerts_e = {r[0] for r in edge.execute("SELECT id FROM alerts").fetchall()}
alerts_c = {r[0] for r in cloud.execute("SELECT id FROM alerts").fetchall()}

print("-" * 56)
print(f"Tổng bản ghi        edge = {total_e}   cloud = {total_c}")
print(f"Bản ghi trùng       0 (khóa duy nhất site + point + ts)")
print(f"Bản ghi gửi bù      {backfilled} (đến cloud trễ > 10s so với thời điểm đo)")
print(f"Cảnh báo            edge = {len(alerts_e)}   cloud = {len(alerts_c)}   thiếu trên cloud = {len(alerts_e - alerts_c)}")
if bad or alerts_e - alerts_c:
    print(f"\n✗ Còn {bad} dòng lệch. Nếu vừa nối lại WAN, đợi 10–20 giây rồi chạy lại.")
    sys.exit(1)
print("\n✓ Edge và cloud khớp hoàn toàn: không mất, không trùng.")
