# GNSS_TEST

衛星測位で遊ぶ。
GNSSログから移動履歴を表示するPythonプロジェクトです。

ZED-F9PのNMEAログを読み、Googleマイマップ用の軌跡ファイルを作るPythonプロジェクトです。
WindowsのPowerShellとuvで実行します。
外部PythonライブラリとGoogle Maps APIキーは不要です。

```text
Tera Termのログ → 有効なGGAを抽出 → DMMからDDへ変換 → KML → Googleマイマップ
```

## Windowsで実行する

1. GitHubの「Code」→「Download ZIP」で取得して展開し、`pyproject.toml` のあるフォルダーを開きます。
2. エクスプローラーのアドレス欄に `powershell` と入力してEnterを押します。
3. 次のコマンドでuvを確認します。

```powershell
uv --version
```

uvが未導入なら、[公式インストール手順](https://docs.astral.sh/uv/getting-started/installation/)に従います。
公式のWindows用コマンドは次のとおりです。

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

インストール後はPowerShellを開き直します。
プロジェクトのフォルダーで次を実行すると、Python 3.12と仮想環境が用意されます。
初回はダウンロードのためインターネット接続が必要になる場合があります。

```powershell
uv sync --locked
```

ログ `2026_10_16_test.txt` をプロジェクトの `data` フォルダーにコピーして、変換します。

```powershell
uv run python -m gnss_maps ".\data\2026_10_16_test.txt" --out ".\result"
```

入力ファイルは書き換えません。
同じ出力先で再実行すると、以下の出力ファイルを上書きします。
計測ごとに残す場合は `--out ".\result\2026-10-16"` のように出力先を変えます。

## Googleマイマップで表示する

1. [Googleマイマップ](https://www.google.com/mymaps)を開き、Googleアカウントでログインします。
2. 「新しい地図を作成」を選びます。
3. レイヤーの「インポート」を選びます。
4. 生成された `result/track.kml` を選びます。

軌跡の線と、開始点および最後の有効な位置が表示されます。
測位が途切れた区間は線を分けています。
計測後の履歴表示に対応するもので、リアルタイム更新や時刻に沿った再生は行いません。
Googleマップのタイムラインへ登録するものでもありません。

[Google公式のインポート手順](https://support.google.com/mymaps/answer/3024836?hl=ja)では、非圧縮KMLの上限は5MBです。
長時間のログで超える場合は、入力ログを計測区間ごとに分けて変換してください。
ログと出力には実際の位置が含まれます。

## 時間別に位置を表示する

通常の変換コマンドで `time_points.kml` も作成します。
マイマップで「レイヤを追加」→「インポート」を選び、このファイルを読み込みます。
軌跡の `track.kml` と別のレイヤーにすると、地点の表示を切り替えられます。
ピンの名前に日本時間の日時を入れてあり、クリックするとUTC、座標、測位状態も確認できます。
レイヤーのスタイル設定でラベルに名前を選ぶと、地図上にも時刻を表示できます。

既定は各区間の最初の点から10秒以上経過した点を順に選びます。
各区間の開始点と終了点も必ず含めるので、区間の端では10秒未満の間隔になる場合があります。
時計の10秒ちょうどの位置を補間する機能ではありません。
軌跡の線には、間引く前のすべての有効な点を使います。

```powershell
# 1秒間隔の地点
uv run python -m gnss_maps ".\data\2026_10_16_test.txt" --out ".\result" --time-step 1

# 全測定点（今回のログは665点）
uv run python -m gnss_maps ".\data\2026_10_16_test.txt" --out ".\result" --time-step 0
```

日付はチェックサムと有効フラグを確認したRMCから取得し、UTC時刻が一致するGGAへ対応付けます。
同じUTC時刻に複数の日付が現れる場合や、対応するRMCがない場合は「日付不明」と表示します。
PCの日付から測定日を推測しません。
対象年は2000〜2099年です。
日本時間への変換では、翌日になる場合も日付を更新します。
`+09:00` は日本時間、`+00:00` はUTCを表します。

マイマップではKMLの時間ベースの要素が読み込まれない場合があるため、通常の地点名と説明に日時を保存しています。
時間スライダーによる再生は、この機能には含めていません。
点が多くて見づらい場合は `--time-step 30` などで間隔を広げます。
長時間のログで地点が2000点を超える場合も、間隔を広げるか計測区間ごとに分けてください。

## 出力ファイル

| ファイル | 用途 |
|---|---|
| `track.kml` | Googleマイマップに読み込む軌跡 |
| `time_points.kml` | 日本時間の名前を付けた地点。既定は10秒間隔 |
| `time_points.csv` | 時刻付き地点の日時、座標、測位状態 |
| `points.csv` | 変換後の座標、UTC時刻、測位状態、区間番号 |
| `summary.json` | 採用件数、除外件数、区間数、最後の有効位置のGoogleマップURL |

`points.csv` の時刻はUTCの `hhmmss.ss` です。
日本時間はUTCに9時間を加えます。
`points.csv` は従来どおりUTC時刻のみです。
`time_points.csv` には、同じUTC時刻の有効なRMCに日付があれば、日本時間とUTCの日時を出力します。
CSVを表計算ソフトで開くと、時刻の先頭の0が省略されることがあります。

## データ形式と変換

**NMEA 0183**は、受信機が測位結果を伝える形式です。
位置の抽出にはGNGGAとGPGGAを使い、日付の取得にはGNRMCとGPRMCを使います。
それ以外の種類の行は読み飛ばします。

```text
$GNGGA,064618.20,3500.00000,N,13900.00000,E,1,09,1.40,163.9,M,36.0,M,,*44
```

上記は説明用の架空データです。

カンマで分割した配列の2番が緯度、3番が南北、4番が経度、5番が東西、6番が測位状態です。
配列の番号は0から数えます。
末尾の `*44` はチェックサムで、伝送時の破損を検査するために使います。

**DMM**は度と小数の分で表した座標です。
NMEAの緯度は `ddmm.mmmmm`、経度は `dddmm.mmmmm` の形式です。
**DD**は度を小数で表した座標で、次の式で変換します。

```text
DD = 度 + 分 / 60
3500.00000,N → 35 + 0 / 60 → 35.00000000
13900.00000,E → 139 + 0 / 60 → 139.00000000
```

南緯Sと西経Wは変換結果を負にします。
この処理は表記の変換であり、測位精度を高める処理ではありません。

Googleマップの検索URLは「緯度,経度」の順です。
KMLは「経度,緯度,高さ」の順です。
本プログラムのKMLは地面に沿って表示する設定を使い、高さの欄は0とします。
受信機の標高を3D表示に使うものではありません。

## 位置を採用する条件

- チェックサムが一致している。
- 座標、方位、UTC時刻が有効な範囲にある。
- GGAの測位状態が1（単独測位）、2（差分補正）、4（RTK FIX）、5（RTK FLOAT）のいずれかである。

測位不可や破損したGGA行を挟んだ場合は、軌跡を別の区間にします。
有効な点の間隔が2秒を超える場合も区間を分けます。
UTCの深夜0時をまたぐ場合は、時刻差を翌日として計算します。
それ以外の時刻の逆転や重複も区間の境界にします。
記録順を保ち、時刻による並べ替えはしません。
複数日のログを結合したものではなく、1回の連続した計測ログを入力してください。

分割する間隔は変更できます。

```powershell
uv run python -m gnss_maps ".\data\2026_10_16_test.txt" --gap-seconds 5
```

GGAに有効と記載されている点でも、実際の位置に誤差がある可能性があります。
異常な位置の飛びを自動除去する処理は含めていません。
区間内の線は測定点を直線で結び、点の間の実際の移動経路は補間しません。

## ファイル構造と役割

以下は、ログを配置して変換した後の構成例です。
`data/measurement.txt` は利用者が用意する入力例、`result/` と `.venv/` は実行時に作られるフォルダーです。
実測ログと変換結果はGitHubには含まれていません。
ZIPで取得した場合、最上位フォルダー名は `GNSS_TEST-main` などになることがあります。

```text
GNSS_TEST/
├── README.md                  # 導入、実行、地図表示、データ形式の説明
├── pyproject.toml             # プロジェクト名、対応Python、依存関係、uv設定
├── uv.lock                    # uvが管理する依存関係の確定情報
├── .python-version            # uvで選択するPythonのバージョン（3.12）
├── .gitignore                 # Gitで管理しないファイルの指定
├── gnss_maps/                 # プログラム本体
│   ├── __init__.py            # Pythonパッケージとしての入口（現在は空）
│   ├── __main__.py            # 実行の入口、引数処理、ログ集計、軌跡出力
│   ├── nmea.py                # GGAの検査とDMM→DD変換
│   └── timed.py               # RMCの日付取得と日時付き地点の出力
├── tests/                     # 変換結果や境界条件を確認するテスト
│   ├── test_track.py          # 座標変換、無効データ、区間分割、KMLの確認
│   └── test_timed.py          # 日付変換、日付欠落、地点の間引きの確認
├── data/                      # 入力ログを置く場所
│   ├── .gitkeep               # 空のフォルダーをGitに残すためのファイル
│   └── measurement.txt        # 利用者がコピーする計測ログの例（未同梱）
├── result/                    # 既定の出力先（変換時に自動作成）
│   ├── track.kml              # 全有効点を結んだ軌跡
│   ├── points.csv             # 全有効点のUTC時刻、座標、測位状態
│   ├── time_points.kml        # 指定間隔で選んだ日時付きピン
│   ├── time_points.csv        # 日時付きピンの日時、座標、測位状態
│   └── summary.json           # 点数、区間数、最後の位置の地図URL
└── .venv/                     # uvが作成する仮想環境（手動編集不要）
```

`data/` の計測ログ、`result/`、`.venv/`、Pythonのキャッシュは `.gitignore` でGitの管理対象から除外しています。
ただし、`--out` で `result/` の外に出力したファイルは、自動で除外されるとは限りません。
フォルダーをZIPで他人に渡す場合も `.gitignore` は働かないため、含めるログと出力結果を確認してください。

### ソースコードを読む順番

| ファイル | 主な関数 | 読むと分かること |
|---|---|---|
| `gnss_maps/__main__.py` | `main()` | コマンド引数を受け取り、各処理をどの順番で実行するか |
| `gnss_maps/nmea.py` | `parse_gga()`、`to_dd()` | NMEAの1行を検査し、緯度と経度を数値に変換する方法 |
| `gnss_maps/__main__.py` | `read_track()`、`seconds()` | 点を集め、測位の途切れや時間差で区間を分ける方法 |
| `gnss_maps/__main__.py` | `write_kml()`、`element()` | 各区間をKMLの線や点として保存する方法 |
| `gnss_maps/timed.py` | `rmc_dates()`、`time_seconds()`、`label_for()` | RMCの日付を同じUTC時刻のGGAに対応付け、日本時間を表示する方法 |
| `gnss_maps/timed.py` | `select_points()`、`write_time_points()` | 指定間隔で点を選び、日時付きKMLとCSVを保存する方法 |

1点のデータは、プログラム内で `(緯度DD, 経度DD, UTC時刻の文字列, 測位状態の文字列)` の順に保持します。
`segments` は「区間の一覧」で、各区間にはこの測定点が記録順に入っています。

```text
main()
├── read_track() → parse_gga() → to_dd()
├── write_kml() → track.kml
├── 全有効点の保存 → points.csv
├── write_time_points()
│   ├── rmc_dates() → 日付の取得
│   ├── select_points() → 地点の選択
│   └── label_for() → time_points.kml / time_points.csv
└── 集計結果の保存 → summary.json
```

### 受け取った人が最初に行うこと

1. `pyproject.toml` のあるフォルダーでPowerShellを開く。
2. `uv sync --locked` で実行環境を用意する。
3. 自分のNMEAログを `data/` にコピーする。
4. 次のコマンドを実行する。ファイル名は実際のログに合わせる。
5. Googleマイマップへ `result/track.kml` と `result/time_points.kml` を別レイヤーとして読み込む。

```powershell
uv run python -m gnss_maps ".\data\measurement.txt" --out ".\result" --time-step 10
```

KMLを作るだけなら、ソースコードを編集する必要はありません。
uvの導入手順は「Windowsで実行する」を参照してください。

## テストと動作確認

```powershell
uv run python -m unittest discover -s tests -v
```

提供されたログで、有効な665点を3区間に分けて出力できることを確認しています。
検証環境はmacOS上のPython 3.14です。
既存の軌跡KMLは利用者の環境でマイマップへの表示を確認済みです。
追加した時刻付き地点はファイル内容を検証済みですが、Windows実機とマイマップでの表示は未検証です。
コードは標準ライブラリのみを使い、Python 3.11以上に対応する構成です。

## 困ったとき

- 「uvが認識されない」：uvの導入後にターミナルを開き直してください。
- 「ファイルを読み書きできません」：ログの場所と名前を確認してください。空白のあるパスは引用符で囲みます。
- 「有効な位置がありません」：ログがGGAを含むか、屋外で測位できていたか確認してください。Tera Termのタイムスタンプ付加はオフにします。
- `gnss_maps` が見つからない：`pyproject.toml` のあるフォルダーで実行してください。

COM3から直接読む機能は、この版には含めていません。
Tera Termでログを保存してから変換します。
直接受信する機能を追加する場合は、COM3の読み取り結果を同じNMEA解析関数へ渡せます。

## 参照資料

- [uvでプロジェクトを実行する](https://docs.astral.sh/uv/concepts/projects/run/)
- [GGAの項目と測位状態](https://www.ardusimple.com/nmea-protocol-and-message-description/nmea-gga-message/)
- [Google Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)
- [KMLの仕様](https://developers.google.com/kml/documentation/kmlreference)
