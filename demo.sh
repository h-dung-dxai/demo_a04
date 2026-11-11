#!/usr/bin/env bash
# Điều khiển demo A04. Xem README.md để biết kịch bản.
set -euo pipefail
cd "$(dirname "$0")"
C="docker compose"
WAN=demo-a04_wan

case "${1:-help}" in
  up)           $C up -d --build
                echo "Mở Grafana: http://localhost:${GRAFANA_PORT:-3300}  (đợi ~20s cho dữ liệu đầu tiên)";;
  down)         $C down -v;;
  status)       $C ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}';;
  alerts)       $C logs -f --since 1m edge-app;;
  heat)         $C exec sim python set_value.py temp "${2:-30}";;
  cool)         $C exec sim python set_value.py temp "${2:-23.5}";;
  load)         $C exec sim python set_value.py load "${2:-85}";;
  wan-cut)      docker network disconnect "$WAN" "$($C ps -q mqtt-cloud)"
                echo "✂  WAN đã CẮT: site01 không còn kết nối tới cloud.";;
  wan-restore)  docker network connect --ip 172.30.0.10 --alias mqtt-cloud "$WAN" "$($C ps -q mqtt-cloud)"
                echo "🔌 WAN đã NỐI LẠI: edge sẽ tự gửi bù dữ liệu.";;
  kill-edge-a)  $C stop telegraf-a mqtt-a
                echo "💥 Edge node A đã TẮT. Edge node B tiếp tục thu thập.";;
  start-edge-a) $C start mqtt-a telegraf-a
                echo "Edge node A đã chạy lại.";;
  reconcile)    $C run --rm tools python -u reconcile.py "${2:-15}";;
  *) cat <<'EOF'
Cách dùng: ./demo.sh <lệnh>
  up | down | status        Dựng / xóa / xem trạng thái demo
  alerts                    Xem log rule engine tại edge (cảnh báo realtime)
  heat [°C] | cool [°C]     Đặt nhiệt độ CRAC-01 (mặc định 30 / 23.5)
  load [%]                  Đặt tải UPS-01 (mặc định 85)
  wan-cut | wan-restore     Cắt / nối lại WAN giữa site và cloud
  kill-edge-a | start-edge-a  Tắt / bật edge node A
  reconcile [phút]          Đối chiếu số bản ghi edge ↔ cloud (mặc định 15 phút)
EOF
esac
