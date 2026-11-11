#!/usr/bin/env bash
# Điều khiển demo A04. Xem README.md để biết kịch bản.
set -euo pipefail
cd "$(dirname "$0")"
C="docker compose"
WAN=demo-a04_wan
SIM="$C exec -T sim python tools/simulator/simctl.py"   # điều khiển simulator modbus-lab (cùng API với trang 5080)

case "${1:-help}" in
  up)           $C up -d --build
                $C logs edge-config
                echo "Mở Grafana:   http://localhost:${GRAFANA_PORT:-3300}  (đợi ~20s cho dữ liệu đầu tiên)"
                echo "Simulator:    http://localhost:${SIM_PORT:-5080}  (đặt giá trị thiết bị, xem khung tin Telegraf đọc)";;
  down)         $C down -v;;
  status)       $C ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}';;
  alerts)       $C logs -f --since 1m edge-app;;
  heat)         $SIM set crah-01.nhiet_do_cap "${2:-31}";;
  cool)         $SIM set crah-01.nhiet_do_cap "${2:-18}";;
  power-fail)   $SIM set ups-01.nguon_ra 5
                echo "⚡ Mất điện lưới: UPS-01 chuyển sang chạy pin.";;
  power-restore) $SIM set ups-01.nguon_ra 3
                echo "Điện lưới có lại: UPS-01 về nguồn lưới.";;
  set)          $SIM set "${2:?thiếu điểm, ví dụ bess-01.muc_pin}" "${3:?thiếu giá trị}";;
  get)          $SIM get ${2:+"$2"};;
  wan-cut)      docker network disconnect "$WAN" "$($C ps -q mqtt-cloud)"
                echo "✂  WAN đã CẮT: site không còn kết nối tới cloud.";;
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
  heat [°C] | cool [°C]     Đặt nhiệt độ gió cấp CRAH-01, BACnet (mặc định 31 / 18)
  power-fail | power-restore  UPS-01 chuyển sang chạy pin / về điện lưới (SNMP)
  set <điểm> <giá trị>      Đặt giá trị bất kỳ điểm nào trong Point Map, ví dụ: set bess-01.muc_pin 15
  get [điểm]                Xem giá trị hiện tại của simulator
  wan-cut | wan-restore     Cắt / nối lại WAN giữa site và cloud
  kill-edge-a | start-edge-a  Tắt / bật edge node A (Telegraf + MQTT)
  reconcile [phút]          Đối chiếu số bản ghi edge ↔ cloud (mặc định 15 phút)
Trang điều khiển simulator: http://localhost:5080 (đổi cổng: SIM_PORT=5090 ./demo.sh up)
EOF
esac
