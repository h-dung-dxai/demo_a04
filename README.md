# Demo A04 – Edge / Cloud: mất WAN, gửi bù, đối chiếu, failover

Tiếng Việt | [日本語](README.ja.md)

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
 Mạng EDGE = mạng OT của container-01 (10.20.0.0/24)          Mạng WAN        Mạng CLOUD
┌────────────────────────────────────────────────────────┐                ┌──────────────────────┐
│  sim (simulator modbus-lab, trang điều khiển :5080)    │                │                      │
│   10.20.0.21:502  gateway Modbus TCP: dong-ho-dien-01/02                │                      │
│   10.20.0.30:502  bess-01 (Modbus TCP, CDAB)           │                │                      │
│   10.20.0.40:161  ups-01 (SNMP)                        │                │                      │
│   10.20.0.50:47808 crah-01 (BACnet/IP)                 │                │                      │
│     │ poll 2s                                          │                │                      │
│     ├── telegraf-a (10.20.0.5) ──► mqtt-a ──bridge QoS1──────────┐      │                      │
│     └── telegraf-b (10.20.0.6) ──► mqtt-b ──bridge QoS1──────────┼──► mqtt-cloud ─► cloud-writer ─► cloud-db
│                          │  │                          │  │  (cắt ở đây)│                      │
│                       edge-app (rule engine)           │                │                      │
│                          │                             │                │                      │
│                       edge-db (TimescaleDB)            │                │                      │
└────────────────────────────────────────────────────────┘                └──────────────────────┘
                        grafana :3300  (trái = edge, phải = cloud)
```

**Thiết bị lấy từ Point Map của modbus-lab** (`../modbus-lab/edge/point-map/devices.yml`). Demo không viết tay thông tin thiết bị nào:
- `sim` chạy simulator của modbus-lab với `--env site`. Container này nhận đúng các IP thật trong Point Map, nên Telegraf kết nối `10.20.0.21:502` như ở site thật.
- `edge-config` chạy một lần mỗi khi `up`. Nó sinh 3 file từ Point Map:
  - cấu hình Telegraf: Modbus TCP và SNMP sinh bằng `generate.py` của modbus-lab, BACnet qua plugin `inputs.execd`;
  - luật cảnh báo cho `edge-app`, lấy từ mục `alerts` của Point Map;
  - dashboard Grafana: phần cố định `grafana/dashboards/a04.json`, ghép thêm thẻ của từng thiết bị.
- **Mọi thiết bị đều đọc bằng Telegraf**, gồm cả BACnet:
  - Telegraf không có plugin đọc BACnet, nên dùng `inputs.execd` chạy script `lab/bacnet_execd.py`.
  - Script dùng lại `bacnet_io.py` của modbus-lab.
  - Telegraf vẫn tự lo việc gửi MQTT và đệm dữ liệu, giống với Modbus và SNMP.
- Sửa Point Map trong modbus-lab, rồi `./demo.sh down && ./demo.sh up`: demo đọc đúng thiết bị mới.
- Repo modbus-lab ở chỗ khác thì chỉ đường dẫn bằng biến `MODBUS_LAB`, ví dụ `MODBUS_LAB=~/src/modbus-lab ./demo.sh up`.

| Thành phần demo | Tương ứng hệ thống thật |
|---|---|
| `sim` (simulator modbus-lab) | Thiết bị thật: gateway đồng hồ điện, BESS, UPS, CRAH (Modbus TCP, SNMP, BACnet/IP) |
| `telegraf-a/b` | Telegraf trên 2 server edge công nghiệp (Modbus, SNMP, BACnet) |
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

- Docker 24 trở lên, có Docker Compose v2.17 trở lên. RAM trống khoảng 2 GB.
- Repo **modbus-lab** đặt cạnh thư mục demo (`../modbus-lab`), hoặc khai báo bằng biến `MODBUS_LAB`.
- Cổng `3300` (Grafana) và `5080` (simulator) còn trống.
  - Nếu cổng đang bận thì đổi cổng: `GRAFANA_PORT=3400 SIM_PORT=5090 ./demo.sh up`.
  - Nếu đang chạy `make sim` của modbus-lab thì cổng 5080 đã bận: dừng `make sim`, hoặc dùng `SIM_PORT`.

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
- Hai bên hiển thị cùng dữ liệu: nhiệt độ gió cấp CRAH-01, công suất 2 đồng hồ điện.
- Cuộn xuống phần "Thiết bị theo Point Map": mỗi thiết bị một thẻ (giao thức, địa chỉ, mọi điểm đo kèm đơn vị). Điểm có luật cảnh báo đổi màu đỏ khi vượt ngưỡng.
- Ô "Giây từ lần nhận dữ liệu cuối" phía cloud có màu xanh, dưới 2 giây.
- Ô "Bản ghi 10 phút qua" ở hai bên bằng nhau.
- Mở tab thứ hai: trang simulator **http://localhost:5080**, phần khung tin. Ở đó thấy Telegraf của 2 edge node lần lượt đọc từng thiết bị, kèm byte thô và giải nghĩa.

> Lời thoại: "Thiết bị ở site nói 3 giao thức: Modbus TCP qua gateway, SNMP và BACnet/IP. Telegraf ở site thu thập cả 3 giao thức, lưu tại chỗ và đồng thời đẩy lên cloud. Danh sách thiết bị và luật cảnh báo đều sinh từ một Point Map. Hai edge node cùng thu thập, nên hỏng một node vẫn không mất dữ liệu."

### Kịch bản 2 – Mất WAN, site vẫn tự vận hành (4 phút)

```bash
./demo.sh wan-cut
```
- Phía cloud: sau khoảng 10 giây, ô trạng thái chuyển đỏ **"SITE MẤT TÍN HIỆU"**, biểu đồ cloud ngừng cập nhật, và mọi thẻ thiết bị phía cloud chuyển sang "—" (không còn số liệu mới).
- Phía edge: biểu đồ vẫn chạy bình thường.

Trong lúc vẫn đang mất WAN, cho nhiệt độ gió cấp CRAH-01 tăng vượt ngưỡng 27 °C. Có thể làm theo một trong hai cách:
- nhập 31 cho `crah-01.nhiet_do_cap` trên trang simulator;
- hoặc chạy lệnh:
```bash
./demo.sh heat 31
```
- Terminal `alerts` hiện dòng đỏ:
  `🚨 [CRITICAL] Gió cấp quá nóng (vượt 27 °C theo ASHRAE) | crah-01.nhiet_do_cap=31.15 | 0.07s kể từ lần đo | CÒI + ĐÈN BẬT`
- Phía edge: ô "Cảnh báo đang bật" chuyển đỏ và bảng cảnh báo edge có dòng mới.
- Phía cloud: chưa biết gì về cảnh báo này, vì đang mất WAN.

Có thể thêm một sự cố nữa: mất điện lưới, UPS chuyển sang chạy pin (đọc qua SNMP):
```bash
./demo.sh power-fail
```
Terminal hiện: `🚨 [CRITICAL] UPS đang chạy bằng pin | ups-01.nguon_ra=5 | …`

> Lời thoại: "Không có WAN nhưng cảnh báo vẫn bật tại site trong vòng dưới 1 giây, vì rule engine chạy ngay tại edge. Đây là yêu cầu D03."

Đưa thiết bị về bình thường:
```bash
./demo.sh cool
./demo.sh power-restore
```
Terminal hiện `✅ Hết cảnh báo` cho từng cảnh báo.

Điểm nào trong Point Map cũng đặt được giá trị, trên trang simulator hoặc bằng lệnh, ví dụ `./demo.sh set bess-01.muc_pin 15` (pin sắp cạn) hoặc `./demo.sh set dong-ho-dien-01.nhiet_do_tu 33` (tủ điện quá nóng).

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
Phút   Điểm đo                        Edge  Cloud  Kết quả
10:13  crah-01.nhiet_do_cap              30     30  ✓ khớp
...
Tổng bản ghi        edge = 1524   cloud = 1524
Bản ghi trùng       0 (khóa duy nhất site + point + ts)
Bản ghi gửi bù      168 (đến cloud trễ > 10s so với thời điểm đo)
Cảnh báo            edge = 2   cloud = 2   thiếu trên cloud = 0
✓ Edge và cloud khớp hoàn toàn: không mất, không trùng.
```

> Lời thoại: "Trong lúc mất WAN, dữ liệu được giữ trong hàng đợi tại site. Khi có mạng lại thì hệ thống tự gửi bù. Script đối chiếu kiểm tra từng phút, từng điểm đo: không mất và không trùng bản ghi nào. Hệ thống thật sẽ chạy job này tự động sau mỗi lần mất kết nối."

### Kịch bản 4 – Một edge node hỏng (3 phút)

```bash
./demo.sh kill-edge-a
```
- Biểu đồ hai bên vẫn liền mạch, không có khoảng trống.
- Terminal `alerts`: `Mất kết nối broker mqtt-a – vẫn nhận dữ liệu qua broker còn lại`.
- Bảng "Giá trị mới nhất" có cột "Edge node": mọi điểm đo chuyển sang `edge-b`.
- Trang simulator, phần khung tin: chỉ còn các lệnh đọc từ edge node B.

```bash
./demo.sh start-edge-a     # bật lại node A
```

> Lời thoại: "Mỗi site có 2 server edge cùng thu thập. Hỏng một server, server còn lại vẫn tiếp tục, và dữ liệu trùng từ hai node được khử tự động bằng khóa duy nhất."

### (Tùy chọn) Kịch bản 5 – Mất liên lạc thiết bị

```bash
docker compose stop sim     # mọi thiết bị ngừng phản hồi
# sau khoảng 10 giây: 🚨 [CRITICAL] Mất liên lạc thiết bị, một cảnh báo cho mỗi thiết bị (5 thiết bị)
docker compose start sim    # simulator chạy lại từ giá trị khởi đầu trong Point Map
```

> Lời thoại: "Mất liên lạc với thiết bị cũng là một cảnh báo, không để hệ thống im lặng."

### Kết thúc
```bash
./demo.sh down     # xóa toàn bộ container và dữ liệu
```

---

## 4. Kết quả đo khi chạy thử (11/11/2026, simulator modbus-lab, 24 điểm đo)

| Chỉ tiêu | Kết quả | Yêu cầu |
|---|---|---|
| Thời gian từ lúc đo đến khi cảnh báo bật tại edge | 0,03 – 0,53 giây | ≤ 10 giây |
| Mất WAN khoảng 30 giây: số bản ghi edge so với cloud (3 phút) | 1524 = 1524, 0 trùng | Không mất, không trùng |
| Cảnh báo phát sinh khi mất WAN có lên tới cloud không | 2/2 | Đầy đủ |
| Tắt edge node A | Mọi điểm chuyển sang edge-b, không có khoảng trống dữ liệu | Không gián đoạn |
| Dừng simulator | 5 cảnh báo mất liên lạc (mỗi thiết bị một), tự hết khi thiết bị trả lời lại | Không im lặng |

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
| Thiết bị là simulator modbus-lab, cùng nằm trong 1 container (mỗi thiết bị một IP) | Thiết bị thật | Không có phần cứng |
| Không đọc `dong-ho-rs485-03` (Modbus RTU qua USB-RS485) | Bus RS-485 cắm vào một server edge | Container không mở được cổng serial ảo của container khác |
| Script BACnet cho Telegraf viết riêng cho demo (`lab/bacnet_execd.py`) | Collector BACnet của dự án | modbus-lab mới có hàm đọc/ghi BACnet, chưa có collector chạy liên tục |
| Mọi cảnh báo trong Point Map đều mức CRITICAL | Mức cảnh báo khai báo trong Point Map | Point Map chưa có trường mức cảnh báo |
| Chưa có lệnh điều khiển (TTL), cờ AI, Mất AZ/DR | Có trong thiết kế | Thuộc bản demo đầy đủ |

---

## 7. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `port is already allocated` | Đổi cổng: `GRAFANA_PORT=3400 SIM_PORT=5090 ./demo.sh up`. Cổng 5080 thường bận vì đang chạy `make sim` của modbus-lab |
| Build lỗi, không tìm thấy `requirements.txt` | Không thấy repo modbus-lab: khai báo `MODBUS_LAB=/đường/dẫn/modbus-lab` |
| Lỗi `Pool overlaps` khi tạo mạng | Một mạng Docker khác đang dùng dải 10.20.0.0/24 (dải IP trong Point Map): xóa mạng đó, hoặc sửa subnet của mạng `edge` và IP trong Point Map |
| `sim` thoát với lỗi "không thuộc mạng edge" | Point Map có IP nằm ngoài dải của mạng `edge` trong `docker-compose.yml`: sửa một trong hai cho khớp |
| Grafana trống dữ liệu | Đợi 20–30 giây, xem `./demo.sh status` để chắc mọi service đang `running` |
| `reconcile` báo LỆCH ngay sau khi nối WAN | Bình thường, vì dữ liệu đang gửi bù. Đợi 20 giây rồi chạy lại |
| `wan-restore` báo lỗi "already exists" | WAN chưa bị cắt, bỏ qua |
| Muốn làm lại từ đầu | `./demo.sh down && ./demo.sh up` |

## 8. Cấu trúc thư mục

```
demo-a04/
├── docker-compose.yml          # 13 service, 3 mạng: edge (10.20.0.0/24) / wan / cloud
├── demo.sh                     # lệnh điều khiển demo
├── telegraf/telegraf.conf      # phần chung của edge: agent + gửi MQTT (thiết bị sinh từ Point Map)
├── mosquitto/edge.conf         # broker edge + bridge store-and-forward
├── mosquitto/cloud.conf
├── lab/                        # chạy code modbus-lab (repo được mount vào /lab); image có cả Telegraf
│   ├── sim_entry.py            # gắn IP thật của thiết bị rồi chạy simulator --env site
│   ├── gen_edge_config.py      # Point Map → inputs Telegraf + luật cảnh báo + thẻ thiết bị trên dashboard
│   └── bacnet_execd.py         # Telegraf chạy script này (inputs.execd) để đọc BACnet
├── app/
│   ├── edge_app.py             # rule engine + ghi TimescaleDB tại edge
│   ├── cloud_writer.py         # phía cloud: ghi DB, khử trùng
│   └── reconcile.py            # đối chiếu edge ↔ cloud
└── grafana/                    # datasource + phần cố định của dashboard (edge-config ghép thêm thẻ thiết bị)
```
