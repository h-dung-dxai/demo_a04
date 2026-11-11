# Demo A04 – Edge / Cloud: mất WAN, gửi bù, đối chiếu, failover

Demo cho **Phần 2 · Phân vai On-prem / Cloud, dự phòng, đồng bộ lại và vận hành khi lỗi** (việc A04, quyết định D03 của biên bản kickoff 06/11/2026).
Chạy hoàn toàn trên 1 máy bằng Docker, không cần thiết bị thật hay tài khoản AWS.

Demo chứng minh 4 điều:

1. **Mất WAN, site vẫn giám sát và cảnh báo**: cảnh báo đỏ bật tại edge dưới 1 giây.
2. **Nối lại WAN, dữ liệu tự gửi bù**: biểu đồ cloud tự lấp khoảng trống.
3. **Không mất, không trùng**: script đối chiếu cho kết quả edge = cloud.
4. **Một edge node hỏng, node còn lại tiếp tục**: dữ liệu không bị gián đoạn.

---

## 1. Kiến trúc demo

```
 Mạng EDGE (OT tại site01)                                   Mạng WAN        Mạng CLOUD
┌────────────────────────────────────────────────────────┐                ┌──────────────────────┐
│  sim (Modbus TCP)                                      │                │                      │
│   CRAC-01, UPS-01                                      │                │                      │
│     │ poll 2s                                          │                │                      │
│     ├── telegraf-a ──► mqtt-a ──bridge QoS1────────────┼──┐             │                      │
│     └── telegraf-b ──► mqtt-b ──bridge QoS1────────────┼──┼──► mqtt-cloud ─► cloud-writer ─► cloud-db
│                          │  │                          │  │  (cắt ở đây)│                      │
│                       edge-app (rule engine)           │                │                      │
│                          │                             │                │                      │
│                       edge-db (TimescaleDB)            │                │                      │
└────────────────────────────────────────────────────────┘                └──────────────────────┘
                        grafana :3300  (trái = edge, phải = cloud)
```

| Thành phần demo | Tương ứng hệ thống thật |
|---|---|
| `sim` (pymodbus) | Thiết bị thật: CRAC, UPS (Modbus TCP) |
| `telegraf-a/b` | Telegraf trên 2 server edge công nghiệp |
| `mqtt-a/b` (Mosquitto + bridge) | MQTT broker tại edge, store-and-forward lên cloud |
| `edge-app` | Rule engine tại edge + ghi TimescaleDB |
| `edge-db` (TimescaleDB) | DB tại edge, lưu 30–90 ngày |
| `mqtt-cloud` | AWS IoT Core |
| `cloud-writer` + `cloud-db` | Kinesis → worker → Aurora PostgreSQL |
| Grafana | Giao diện Nuxt (site và trung tâm) |
| Dòng log `🚨 … CÒI + ĐÈN BẬT` | Còi, đèn, SMS 4G |

**Quy tắc đồng bộ được demo** (theo mục 2.3 của tài liệu so sánh):
- Khóa duy nhất `(site, point, ts)` + `ON CONFLICT DO NOTHING`: dữ liệu đến 2 lần (từ 2 edge node, hoặc gửi lại sau khi mất WAN) không bị trùng.
- Thời điểm đo do edge gắn, không dùng giờ cloud nhận. Cột `received_at` trên cloud cho biết bản ghi nào được gửi bù.
- Cảnh báo có `id` (UUID) do edge sinh ra, nên cloud gộp lại mà không tạo cảnh báo trùng.

---

## 2. Chuẩn bị

- Docker 24 trở lên, có Docker Compose v2. RAM trống khoảng 2 GB.
- Cổng `3300` còn trống. Nếu cổng đang bận thì đổi cổng: `GRAFANA_PORT=3400 ./demo.sh up`.

```bash
cd demo-a04
./demo.sh up          # lần đầu mất 1–3 phút để tải image
```

Mở **http://localhost:3300** và đợi khoảng 20 giây để có dữ liệu đầu tiên. Không cần đăng nhập.
Mở thêm một terminal để xem rule engine tại edge chạy realtime:

```bash
./demo.sh alerts
```

> Nên dựng demo **trước buổi trình bày ít nhất 5 phút** để biểu đồ đã có dữ liệu.

---

## 3. Kịch bản trình bày (khoảng 15 phút)

### Kịch bản 1 – Vận hành bình thường (2 phút)

Màn hình chia hai nửa: **trái = edge tại site**, **phải = cloud AWS**.
- Hai bên hiển thị cùng dữ liệu nhiệt độ CRAC-01 và tải UPS-01.
- Ô "Giây từ lần nhận dữ liệu cuối" phía cloud có màu xanh, dưới 2 giây.
- Ô "Bản ghi 10 phút qua" ở hai bên bằng nhau.

> Lời thoại: "Dữ liệu được thu thập ở site bằng Telegraf, lưu tại chỗ và đồng thời đẩy lên cloud. Hai edge node cùng thu thập, nên hỏng một node vẫn không mất dữ liệu."

### Kịch bản 2 – Mất WAN, site vẫn tự vận hành (4 phút)

```bash
./demo.sh wan-cut
```
- Phía cloud: sau khoảng 10 giây, ô trạng thái chuyển đỏ **"SITE MẤT TÍN HIỆU"** và biểu đồ cloud ngừng cập nhật.
- Phía edge: biểu đồ vẫn chạy bình thường.

Trong lúc vẫn đang mất WAN, cho nhiệt độ CRAC tăng vượt ngưỡng 27 °C:
```bash
./demo.sh heat 31
```
- Terminal `alerts` hiện dòng đỏ:
  `🚨 [CRITICAL] Nhiệt độ gió cấp CRAC-01 cao | crac01.supply_temp=31.1 | 0.28s kể từ lần đo | CÒI + ĐÈN BẬT`
- Phía edge: ô "Cảnh báo đang bật" chuyển đỏ và bảng cảnh báo edge có dòng mới.
- Phía cloud: chưa biết gì về cảnh báo này, vì đang mất WAN.

> Lời thoại: "Không có WAN nhưng cảnh báo vẫn bật tại site trong vòng dưới 1 giây, vì rule engine chạy ngay tại edge. Đây là yêu cầu D03."

Hạ nhiệt độ trở lại:
```bash
./demo.sh cool
```
Terminal hiện `✅ Hết cảnh báo`.

### Kịch bản 3 – Nối lại WAN, gửi bù và đối chiếu (4 phút)

```bash
./demo.sh wan-restore
```
- Phía cloud: ô trạng thái về xanh. **Khoảng trống trên biểu đồ cloud được lấp đầy**, kể cả đoạn nhiệt độ vượt ngưỡng.
- Bảng "Cảnh báo cloud nhận được từ edge" xuất hiện cảnh báo đã xảy ra trong lúc mất WAN, với đúng thời điểm bật và tắt.

Đợi khoảng 1 phút để phút đang ghi dở kết thúc, rồi chạy đối chiếu:
```bash
./demo.sh reconcile 10
```
Kết quả mong đợi:
```
Phút   Điểm đo                  Edge  Cloud  Kết quả
16:46  crac01.supply_temp         30     30  ✓ khớp
...
Tổng bản ghi        edge = 198   cloud = 198
Bản ghi trùng       0 (khóa duy nhất site + point + ts)
Bản ghi gửi bù      36 (đến cloud trễ > 10s so với thời điểm đo)
Cảnh báo            edge = 3   cloud = 3   thiếu trên cloud = 0
✓ Edge và cloud khớp hoàn toàn: không mất, không trùng.
```

> Lời thoại: "Trong lúc mất WAN, dữ liệu được giữ trong hàng đợi tại site. Khi có mạng lại thì hệ thống tự gửi bù. Script đối chiếu kiểm tra từng phút, từng điểm đo: không mất và không trùng bản ghi nào. Hệ thống thật sẽ chạy job này tự động sau mỗi lần mất kết nối."

### Kịch bản 4 – Một edge node hỏng (3 phút)

```bash
./demo.sh kill-edge-a
```
- Biểu đồ hai bên vẫn liền mạch, không có khoảng trống.
- Terminal `alerts`: `Mất kết nối broker mqtt-a – vẫn nhận dữ liệu qua broker còn lại`.
- Có thể kiểm tra: dữ liệu mới chỉ còn đến từ `edge-b`.

```bash
./demo.sh start-edge-a     # bật lại node A
```

> Lời thoại: "Mỗi site có 2 server edge cùng thu thập. Hỏng một server, server còn lại vẫn tiếp tục, và dữ liệu trùng từ hai node được khử tự động bằng khóa duy nhất."

### (Tùy chọn) Kịch bản 5 – Mất liên lạc thiết bị

```bash
docker compose stop sim     # thiết bị ngừng phản hồi
# sau khoảng 10 giây: 🚨 [CRITICAL] Mất liên lạc thiết bị
docker compose start sim
```

> Lời thoại: "Mất liên lạc với thiết bị cũng là một cảnh báo, không để hệ thống im lặng."

### Kết thúc
```bash
./demo.sh down     # xóa toàn bộ container và dữ liệu
```

---

## 4. Kết quả đo khi chạy thử (10/11/2026)

| Chỉ tiêu | Kết quả | Yêu cầu |
|---|---|---|
| Thời gian từ lúc đo đến khi cảnh báo bật tại edge | 0,28 – 0,97 giây | ≤ 10 giây |
| Mất WAN khoảng 1 phút: số bản ghi edge so với cloud | 198 = 198, 0 trùng | Không mất, không trùng |
| Cảnh báo phát sinh khi mất WAN có lên tới cloud không | 3/3 | Đầy đủ |
| Tắt edge node A | Không có khoảng trống dữ liệu | Không gián đoạn |

Chưa tính thời gian poll: thiết bị được poll mỗi 2 giây, nên thời gian từ lúc giá trị thay đổi đến khi có cảnh báo tối đa khoảng 3 giây.

---

## 5. Phát hiện kỹ thuật khi làm demo (đưa vào thiết kế thật)

1. **Bridge MQTT không được phụ thuộc DNS.**
   - Ở bản đầu, bridge Mosquitto kết nối cloud bằng tên miền. Khi mất WAN, mỗi lần thử kết nối lại thì phân giải DNS treo vài giây, kéo theo **toàn bộ broker tại edge bị treo**. Rule engine bị ngắt kết nối và edge mất dữ liệu.
   - Đã sửa bằng cách cấu hình bridge theo IP cố định.
   - Với hệ thống thật cần xử lý tương tự: dùng IP hoặc DNS cache cục bộ, và kiểm thử "mất WAN" phải là một test case bắt buộc của GĐ1.
2. **Rule engine phải dùng phiên MQTT bền** (`clean_session=False`), để broker giữ tin nhắn trong thời gian rule engine khởi động lại.
3. **Thứ tự khởi động:** chỉ bắt đầu thu thập khi rule engine tại edge đã sẵn sàng. Nếu không, các bản ghi đầu tiên chỉ có trên cloud mà không có ở edge.

---

## 6. Những gì demo đơn giản hóa so với thiết kế thật

| Demo | Thiết kế thật | Lý do đơn giản hóa |
|---|---|---|
| 2 edge node cùng thu thập (active-active) + khử trùng | Active-Standby với VIP (keepalived) và fencing | Ít thành phần hơn mà vẫn thể hiện được failover. Active-active cũng là một phương án hợp lệ |
| 1 edge-db dùng chung cho 2 node | TimescaleDB trên mỗi node + streaming replication | Demo tập trung vào luồng edge ↔ cloud |
| `mqtt-cloud` + PostgreSQL | AWS IoT Core + Kinesis + Aurora (Multi-AZ) | Không cần tài khoản AWS. Đổi sang AWS ở GĐ1 |
| Không có TLS, không có xác thực MQTT | mTLS (chứng chỉ thiết bị IoT Core), TLS 1.3 | Chỉ chạy nội bộ trên laptop |
| Còi/đèn/SMS là dòng log và ô màu đỏ | Relay còi/đèn, modem 4G | Không có phần cứng |
| Chỉ Modbus | SNMP, Modbus, BACnet | Thêm snmpsim/bacpypes3 ở GĐ1 |
| Chưa có lệnh điều khiển (TTL), cờ AI, Mất AZ/DR | Có trong thiết kế | Thuộc bản demo đầy đủ |

---

## 7. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `port is already allocated` | Đổi cổng: `GRAFANA_PORT=3400 ./demo.sh up` |
| Grafana trống dữ liệu | Đợi 20–30 giây, xem `./demo.sh status` để chắc mọi service đang `running` |
| `reconcile` báo LỆCH ngay sau khi nối WAN | Bình thường, vì dữ liệu đang gửi bù. Đợi 20 giây rồi chạy lại |
| `wan-restore` báo lỗi "already exists" | WAN chưa bị cắt, bỏ qua |
| Muốn làm lại từ đầu | `./demo.sh down && ./demo.sh up` |

## 8. Cấu trúc thư mục

```
demo-a04/
├── docker-compose.yml          # 11 service, 3 mạng: edge / wan / cloud
├── demo.sh                     # lệnh điều khiển demo
├── telegraf/telegraf.conf      # Modbus → MQTT
├── mosquitto/edge.conf         # broker edge + bridge store-and-forward
├── mosquitto/cloud.conf
├── app/
│   ├── sim.py                  # thiết bị giả lập Modbus TCP
│   ├── set_value.py            # đổi nhiệt độ / tải giả lập
│   ├── edge_app.py             # rule engine + ghi TimescaleDB tại edge
│   ├── rules.json              # ngưỡng cảnh báo
│   ├── cloud_writer.py         # phía cloud: ghi DB, khử trùng
│   └── reconcile.py            # đối chiếu edge ↔ cloud
└── grafana/                    # datasource + dashboard tự cấu hình
```
