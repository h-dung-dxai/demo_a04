# デモ A04 – Edge / Cloud：WAN 断、再送、突合、フェイルオーバー

[Tiếng Việt](README.md) | 日本語

**第2部・オンプレ／クラウドの役割分担、冗長化、再同期、障害時運用**のデモです（キックオフ議事録 2026/11/06 の課題 A04、決定事項 D03）。
Docker で 1 台の PC 上だけで動作し、実機や AWS アカウントは不要です。

このデモで示すこと：

1. **WAN が切れてもサイトは監視・警報を継続**：Edge で 1 秒未満に赤警報が発報される。
2. **WAN 復旧後、データを自動再送**：クラウド側グラフの欠損が自動で埋まる。
3. **欠損なし・重複なし**：突合スクリプトで Edge = Cloud を確認。
4. **Edge ノード 1 台が故障しても、もう 1 台で継続**：データが途切れない。

> 注：画面（Grafana のパネル名）、ターミナル出力、シミュレータの点名はベトナム語のままです。本書では該当箇所に「ベトナム語表記（日本語訳）」を併記しています。

---

## 1. デモ構成

```
 EDGE ネットワーク = container-01 の OT ネットワーク (10.20.0.0/24)      WAN            CLOUD
┌────────────────────────────────────────────────────────┐                ┌──────────────────────┐
│  sim (modbus-lab シミュレータ、操作画面 :5080)         │                │                      │
│   10.20.0.21:502  Modbus TCP ゲートウェイ: dong-ho-dien-01/02           │                      │
│   10.20.0.30:502  bess-01 (Modbus TCP, CDAB)           │                │                      │
│   10.20.0.40:161  ups-01 (SNMP)                        │                │                      │
│   10.20.0.50:47808 crah-01 (BACnet/IP)                 │                │                      │
│   10.20.0.60:7000 RS-485 バス /dev/ttyUSB0（TCP 経由）: dong-ho-rs485-03 (Modbus RTU)            │
│     │ 2 秒周期でポーリング                             │                │                      │
│     ├── telegraf-a (10.20.0.5) ──► mqtt-a ──bridge QoS1──────────┐      │                      │
│     └── telegraf-b (10.20.0.6) ──► mqtt-b ──bridge QoS1──────────┼──► mqtt-cloud ─► cloud-writer ─► cloud-db
│                          │  │                          │  │ (ここを切断)│                      │
│                       edge-app (ルールエンジン)        │                │                      │
│                          │                             │                │                      │
│                       edge-db (TimescaleDB)            │                │                      │
└────────────────────────────────────────────────────────┘                └──────────────────────┘
                        grafana :3300  (左 = Edge、右 = Cloud)
```

**機器情報は modbus-lab の Point Map から取得**します（`../modbus-lab/edge/point-map/devices.yml`）。デモ内に機器情報の手書きはありません。
- `sim` は modbus-lab のシミュレータを `--env site` で起動します。このコンテナは Point Map 上の実 IP をそのまま持つため、Telegraf は実サイトと同様に `10.20.0.21:502` へ接続します。
- `edge-config` は `up` のたびに 1 回だけ実行され、Point Map から 3 つのファイルを生成します：
  - Telegraf 設定：Modbus TCP と SNMP は modbus-lab の `generate.py` で生成、BACnet は `inputs.execd` プラグイン経由；
  - `edge-app` 用の警報ルール：Point Map の `alerts` 項目から生成；
  - Grafana ダッシュボード（ベトナム語 `a04`、日本語 `a04-ja`）：固定部分 `grafana/dashboards/a04.json` に機器ごとのカードを追加。日本語版は `grafana/dashboards/translations.ja.json` で翻訳し、機器名・計測点名・警報内容は Point Map の `ja` ラベルを使用。
- **全機器を Telegraf で読み取ります**（BACnet を含む）：
  - Telegraf には BACnet 読み取りプラグインがないため、`inputs.execd` でスクリプト `lab/bacnet_execd.py` を実行します。
  - このスクリプトは modbus-lab の `bacnet_io.py` を再利用しています。
  - MQTT 送信とバッファリングは Modbus・SNMP と同様に Telegraf が担います。
- modbus-lab の Point Map を修正したら `./demo.sh down && ./demo.sh up` を実行すると、新しい機器構成で動作します。
- modbus-lab リポジトリが別の場所にある場合は、環境変数 `MODBUS_LAB` でパスを指定します。例：`MODBUS_LAB=~/src/modbus-lab ./demo.sh up`

| デモの構成要素 | 本番システムでの対応 |
|---|---|
| `sim`（modbus-lab シミュレータ） | 実機：電力計ゲートウェイ、BESS、UPS、CRAH（Modbus TCP、SNMP、BACnet/IP） |
| `telegraf-a/b` | 産業用 Edge サーバ 2 台上の Telegraf（Modbus、SNMP、BACnet） |
| `mqtt-a/b`（Mosquitto + bridge） | Edge の MQTT ブローカ、クラウドへのストア＆フォワード |
| `edge-app` | Edge のルールエンジン + TimescaleDB 書き込み |
| `edge-db`（TimescaleDB） | Edge の DB、30〜90 日保存 |
| `mqtt-cloud` | AWS IoT Core |
| `cloud-writer` + `cloud-db` | Kinesis → worker → Aurora PostgreSQL |
| Grafana | Nuxt 画面（サイト用・センター用） |
| ログ行 `🚨 … CÒI + ĐÈN BẬT`（ブザー＋警告灯 ON） | ブザー、警告灯、4G 経由 SMS |

**デモで示す同期ルール**（方式比較資料 2.3 節に準拠）：
- 一意キー `(site, point, ts)` + `ON CONFLICT DO NOTHING`：同じデータが 2 回届いても（Edge ノード 2 台から、または WAN 断後の再送）重複しません。
- 計測時刻は Edge が付与し、クラウドの受信時刻は使いません。クラウド側の `received_at` 列で再送されたレコードを判別できます。
- 警報には Edge が生成した `id`（UUID）が付くため、クラウドで集約しても警報が重複しません。

---

## 2. 準備

- Docker 24 以上、Docker Compose v2.17 以上。空きメモリ約 2 GB。
- **modbus-lab** リポジトリをデモフォルダの隣（`../modbus-lab`）に置くか、環境変数 `MODBUS_LAB` で指定します。
- ポート `3300`（Grafana）と `5080`（シミュレータ）が空いていること。
  - 使用中の場合はポートを変更：`GRAFANA_PORT=3400 SIM_PORT=5090 ./demo.sh up`
  - modbus-lab の `make sim` を実行中だと 5080 が使用中になります。`make sim` を停止するか、`SIM_PORT` を使ってください。

```bash
cd demo-a04
./demo.sh up          # 初回はイメージ取得に 1〜3 分
```

**http://localhost:3300** を開き、最初のデータが来るまで約 20 秒待ちます。ログインは不要です。
右上の **Tiếng Việt** / **日本語** ボタンでダッシュボードの言語を切り替えます（日本語版：http://localhost:3300/d/a04-ja）。
もう 1 つターミナルを開き、Edge のルールエンジンの動きをリアルタイムで表示します：

```bash
./demo.sh alerts
```

> グラフにデータが溜まるよう、**発表の 5 分以上前に**起動しておくことを推奨します。

---

## 3. 発表シナリオ（約 15 分）

### シナリオ 1 – 通常運用（2 分）

画面は左右 2 分割：**左 = サイトの Edge**、**右 = AWS クラウド**。
- 両側に同じデータが表示されます：CRAH-01 の給気温度、電力計 2 台の電力。
- 「Thiết bị theo Point Map」（Point Map の機器一覧）までスクロール：機器ごとにカードが 1 枚（プロトコル、アドレス、全計測点と単位）。警報ルールのある点は閾値を超えると赤になります。
- クラウド側の「Giây từ lần nhận dữ liệu cuối」（最終受信からの秒数）は緑、2 秒未満。
- 「Bản ghi 10 phút qua」（直近 10 分のレコード数）は左右で同じ値。
- 2 つ目のタブでシミュレータ画面 **http://localhost:5080** のフレーム欄を開くと、Edge ノード 2 台の Telegraf が各機器を順番に読み取る様子が、生バイトと解読結果付きで見られます。

> トーク例：「サイトの機器は Modbus TCP（ゲートウェイ経由）、SNMP、BACnet/IP の 3 プロトコルです。サイトの Telegraf が 3 プロトコルすべてを収集し、ローカルに保存すると同時にクラウドへ送ります。機器一覧も警報ルールも 1 つの Point Map から生成しています。Edge ノード 2 台で収集しているので、1 台故障してもデータは失われません。」

### シナリオ 2 – WAN 断でもサイトは自律運用（4 分）

```bash
./demo.sh wan-cut
```
- クラウド側：約 10 秒後、ステータス欄が赤 **「SITE MẤT TÍN HIỆU」（サイト信号途絶）** に変わり、クラウドのグラフは更新停止、クラウド側の機器カードはすべて「—」（新しい値なし）になります。
- Edge 側：グラフは通常どおり動き続けます。

WAN 断のまま、CRAH-01 の給気温度を閾値 27 °C 超に上げます。次のどちらかで操作します：
- シミュレータ画面で `crah-01.nhiet_do_cap` に 31 を入力；
- またはコマンド：
```bash
./demo.sh heat 31
```
- `alerts` ターミナルに赤い行が表示されます：
  `🚨 [CRITICAL] Gió cấp quá nóng (vượt 27 °C theo ASHRAE) | crah-01.nhiet_do_cap=31.15 | 0.07s kể từ lần đo | CÒI + ĐÈN BẬT`
  （給気温度過高（ASHRAE の 27 °C 超過）｜計測から 0.07 秒｜ブザー＋警告灯 ON）
- Edge 側：「Cảnh báo đang bật」（発報中の警報）が赤になり、Edge の警報表に新しい行が追加されます。
- クラウド側：WAN 断中のため、この警報はまだ届いていません。

追加の障害として、商用電源喪失で UPS がバッテリー運転に切り替わる状況も再現できます（SNMP で読み取り）：
```bash
./demo.sh power-fail
```
ターミナル表示：`🚨 [CRITICAL] UPS đang chạy bằng pin | ups-01.nguon_ra=5 | …`（UPS バッテリー運転中）

> トーク例：「WAN がなくても、ルールエンジンが Edge で動いているので、1 秒未満でサイトに警報が出ます。これが要件 D03 です。」

機器を正常値に戻します：
```bash
./demo.sh cool
./demo.sh power-restore
```
ターミナルに警報ごとに `✅ Hết cảnh báo`（警報解除）が表示されます。

Point Map のどの点でも、シミュレータ画面またはコマンドで値を設定できます。例：`./demo.sh set bess-01.muc_pin 15`（バッテリー残量低下）、`./demo.sh set dong-ho-dien-01.nhiet_do_tu 33`（盤内温度過高）。

### シナリオ 3 – WAN 復旧、再送と突合（4 分）

```bash
./demo.sh wan-restore
```
- クラウド側：ステータス欄が緑に戻り、**クラウドのグラフの欠損が埋まります**（閾値超過の区間も含む）。
- 「Cảnh báo cloud nhận được từ edge」（クラウドが Edge から受信した警報）表に、WAN 断中に発生した警報が正しい発報・解除時刻で表示されます。

記録中の 1 分が終わるまで約 1 分待ってから突合を実行します：
```bash
./demo.sh reconcile 10
```
期待される結果（出力はベトナム語。Khớp = 一致、Tổng bản ghi = 総レコード数、Bản ghi trùng = 重複、Bản ghi gửi bù = 再送、Cảnh báo = 警報）：
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

> トーク例：「WAN 断の間、データはサイトのキューに保持され、回線が戻ると自動で再送されます。突合スクリプトで 1 分ごと・計測点ごとに確認し、欠損も重複も 1 件もありません。本番では回線断のたびにこのジョブを自動実行します。」

### シナリオ 4 – Edge ノード 1 台の故障（3 分）

```bash
./demo.sh kill-edge-a
```
- 左右のグラフは途切れずに続きます。
- `alerts` ターミナル：`Mất kết nối broker mqtt-a – vẫn nhận dữ liệu qua broker còn lại`（mqtt-a 切断 – 残りのブローカ経由で受信継続）
- 「Giá trị mới nhất」（最新値）表の「Edge node」列：全計測点が `edge-b` に切り替わります。
- シミュレータ画面のフレーム欄：Edge ノード B からの読み取りだけになります。

```bash
./demo.sh start-edge-a     # ノード A を再起動
```

> トーク例：「各サイトには Edge サーバが 2 台あり、両方で収集しています。1 台が故障しても残りが継続し、2 台からの重複データは一意キーで自動的に除去されます。」

### （任意）シナリオ 5 – 機器との通信途絶

```bash
docker compose stop sim     # 全機器が応答停止
# 約 10 秒後：🚨 [CRITICAL] Mất liên lạc thiết bị（機器通信途絶）、機器ごとに 1 件（6 機器）
docker compose start sim    # シミュレータは Point Map の初期値から再開
```

> トーク例：「機器との通信途絶も警報になります。システムが黙り込むことはありません。」

### 終了
```bash
./demo.sh down     # 全コンテナとデータを削除
```

---

## 4. 試験結果（2026/11/11、modbus-lab シミュレータ、計測点 24）

| 指標 | 結果 | 要件 |
|---|---|---|
| 計測から Edge で警報発報までの時間 | 0.03〜0.53 秒 | 10 秒以内 |
| 約 30 秒の WAN 断：Edge と Cloud のレコード数（3 分間） | 1524 = 1524、重複 0 | 欠損なし・重複なし |
| WAN 断中に発生した警報がクラウドに届くか | 2/2 | 全件 |
| Edge ノード A 停止 | 全計測点が edge-b に切替、データ欠損なし | 中断なし |
| シミュレータ停止 | 通信途絶警報 5 件（機器ごとに 1 件）、応答再開で自動解除 | 沈黙しない |

ポーリング時間は含みません。機器は 2 秒周期でポーリングするため、値の変化から警報までは最大約 3 秒です。

---

## 5. デモ作成で得た技術的知見（本番設計に反映）

1. **MQTT ブリッジを DNS に依存させない。**
   - 初版では Mosquitto のブリッジがドメイン名でクラウドに接続していました。WAN 断中は再接続のたびに DNS 解決が数秒ハングし、**Edge のブローカ全体が停止**。ルールエンジンが切断され、Edge でデータが失われました。
   - ブリッジを固定 IP 指定にして解決しました。
   - 本番でも同様の対応が必要です：IP 指定またはローカル DNS キャッシュを使い、「WAN 断」試験をフェーズ 1 の必須テストケースとします。
2. **ルールエンジンは永続 MQTT セッション**（`clean_session=False`）を使い、再起動中のメッセージをブローカに保持させる。
3. **起動順序**：Edge のルールエンジンの準備完了後に収集を開始する。そうしないと最初のレコードがクラウドにだけ存在し、Edge に残りません。

---

## 6. 本番設計からの簡略化

| デモ | 本番設計 | 簡略化の理由 |
|---|---|---|
| Edge ノード 2 台で同時収集（Active-Active）+ 重複除去 | VIP（keepalived）と fencing による Active-Standby | 構成要素を減らしつつフェイルオーバーを示せる。Active-Active も有効な選択肢 |
| 2 ノードで edge-db を 1 つ共用 | 各ノードに TimescaleDB + ストリーミングレプリケーション | デモの焦点は Edge ↔ Cloud の流れ |
| `mqtt-cloud` + PostgreSQL | AWS IoT Core + Kinesis + Aurora（Multi-AZ） | AWS アカウント不要。フェーズ 1 で AWS に移行 |
| TLS なし、MQTT 認証なし | mTLS（IoT Core のデバイス証明書）、TLS 1.3 | ノート PC 内のみで動作 |
| ブザー／警告灯／SMS はログ行と赤いパネル | ブザー・警告灯用リレー、4G モデム | ハードウェアなし |
| 機器は modbus-lab シミュレータ、1 コンテナ内（機器ごとに IP） | 実機 | ハードウェアなし |
| `dong-ho-rs485-03` の RS-485 バスは模擬シリアル↔Ethernet 変換器（`10.20.0.60:7000`、RTU over TCP）経由で、Edge ノード 2 台が読む | RS-485 バスを USB で Edge サーバ 1 台に接続、またはシリアル↔Ethernet 変換器経由 | コンテナから別コンテナの仮想シリアルポートを開けない。バスのアドレスは `docker-compose.yml` の `x-serial-tcp` で定義 |
| Telegraf 用 BACnet スクリプトはデモ専用（`lab/bacnet_execd.py`） | プロジェクトの BACnet コレクタ | modbus-lab には BACnet 読み書き関数のみで、常駐コレクタはまだない |
| Point Map の警報はすべて CRITICAL | 警報レベルを Point Map で定義 | Point Map に警報レベルの項目がまだない |
| 制御コマンド（TTL）、AI フラグ、AZ 障害／DR は未実装 | 設計には含まれる | フルデモ版の範囲 |

---

## 7. トラブルシューティング

| 症状 | 対処 |
|---|---|
| `port is already allocated` | ポート変更：`GRAFANA_PORT=3400 SIM_PORT=5090 ./demo.sh up`。5080 は modbus-lab の `make sim` 実行中で使用されていることが多い |
| ビルドエラー、`requirements.txt` が見つからない | modbus-lab リポジトリが見つからない：`MODBUS_LAB=/path/to/modbus-lab` を指定 |
| ネットワーク作成時に `Pool overlaps` | 別の Docker ネットワークが 10.20.0.0/24（Point Map の IP 帯）を使用中：そのネットワークを削除するか、`edge` ネットワークのサブネットと Point Map の IP を変更 |
| `sim` が「không thuộc mạng edge」（edge ネットワーク外）で終了 | Point Map の IP が `docker-compose.yml` の `edge` ネットワーク範囲外：どちらかを修正して一致させる |
| Grafana にデータがない | 20〜30 秒待ち、`./demo.sh status` で全サービスが `running` か確認 |
| WAN 復旧直後に `reconcile` が「LỆCH」（不一致）を表示 | 再送中のため正常。20 秒待って再実行 |
| `wan-restore` が「already exists」エラー | WAN が切断されていないだけなので無視 |
| 最初からやり直したい | `./demo.sh down && ./demo.sh up` |

## 8. ディレクトリ構成

```
demo-a04/
├── docker-compose.yml          # 13 サービス、3 ネットワーク：edge (10.20.0.0/24) / wan / cloud
├── demo.sh                     # デモ操作コマンド
├── telegraf/telegraf.conf      # Edge 共通部分：agent + MQTT 送信（機器は Point Map から生成）
├── mosquitto/edge.conf         # Edge ブローカ + ストア＆フォワード用ブリッジ
├── mosquitto/cloud.conf
├── lab/                        # modbus-lab のコードを実行（リポジトリを /lab にマウント）、イメージに Telegraf も同梱
│   ├── sim_entry.py            # 機器の実 IP を付与してシミュレータを --env site で起動
│   ├── gen_edge_config.py      # Point Map → Telegraf inputs + 警報ルール + ダッシュボードの機器カード
│   └── bacnet_execd.py         # Telegraf がこのスクリプトを実行（inputs.execd）して BACnet を読む
├── app/
│   ├── edge_app.py             # ルールエンジン + Edge の TimescaleDB 書き込み
│   ├── cloud_writer.py         # クラウド側：DB 書き込み、重複除去
│   └── reconcile.py            # Edge ↔ Cloud 突合
└── grafana/                    # データソース + ダッシュボード固定部分（edge-config が機器カードを追加）
```
