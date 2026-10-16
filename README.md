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

## 出力ファイル

| ファイル | 用途 |
|---|---|
| `track.kml` | Googleマイマップに読み込む軌跡 |
| `points.csv` | 変換後の座標、UTC時刻、測位状態、区間番号 |
| `summary.json` | 採用件数、除外件数、区間数、最後の有効位置のGoogleマップURL |

CSVの時刻はUTCの `hhmmss.ss` です。
日本時間はUTCに9時間を加えます。
GGA自体には日付がないため、この版では日付を出力しません。
CSVを表計算ソフトで開くと、時刻の先頭の0が省略されることがあります。

## データ形式と変換

**NMEA 0183**は、受信機が測位結果を伝える形式です。
このプログラムはGNGGAとGPGGAを読み、RMCなどのほかの行は読み飛ばします。

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

## プロジェクト構成と確認

- `gnss_maps/nmea.py`：NMEAの検査と座標変換。
- `gnss_maps/__main__.py`：ログ読み取り、区間分割、KMLなどの出力。
- `tests/test_track.py`：符号、無効な位置、チェックサム、日付境界、区間分割、KML座標順の確認。
- `pyproject.toml`：Pythonバージョンとプロジェクト設定。
- `uv.lock`：uvのロックファイル。

```powershell
uv run python -m unittest discover -s tests -v
```

提供されたログで、有効な665点を3区間に分けて出力できることを確認しています。
検証環境はmacOS上のPython 3.14です。
Windows実機およびGoogleマイマップへの実アップロードは未検証です。
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
