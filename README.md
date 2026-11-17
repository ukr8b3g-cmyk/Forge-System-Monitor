# Forge System Monitor

Forge Neo と reForge の生成画面に、CPU・RAM・GPU・VRAM・GPU 温度を表示する拡張です。RAM と VRAM は使用率と使用量／総量を表示します。

## 導入

1. この `Forge-System-Monitor` フォルダーを WebUI の `extensions` にコピーします。
2. WebUI を再起動します。
3. 上部の **Settings** タブを開き、左メニューの **Extensions → System Monitor**（システムモニター）を選びます。

初期位置は `txt2img` と `img2img` の生成操作欄の下です。EasyPromptSelector がある場合はタグ選択の直下に表示されます。Compact UI では Generate の直下に配置します。

| 設定 | 選択肢・動作 |
| --- | --- |
| 表示位置 | 生成欄の下（既定）／フローティング。フローティングのときだけ四隅から固定位置を選べます。 |
| 表示言語 | `Auto`（既定）／`English`／`Japanese`。自動は WebUI のロケールに従い、日本語以外では英語を表示します。 |
| 監視する GPU | 自動または検出した GPU の機種名。自動は、GPU が1台ならその GPU、複数台なら WebUI の使用デバイスを識別できた場合にその GPU を表示します。 |
| 表示項目と更新 | CPU、RAM、GPU、VRAM、GPU 温度を個別に選択できます。更新間隔は1秒、2秒（既定）、5秒です。 |

変更は標準の **Apply settings** で反映します。全体をオフにしたときや、生成画面・ブラウザータブを離れたときは更新を止めます。表示言語の選択はモニター本体に適用されます。

## 計測

CPU と RAM は WebUI 環境に含まれる `psutil` で読み取ります。Windows では Windows の GPU カウンターから GPU 使用率と専用 VRAM を、ドライバーが提供する場合は GPU 温度も読み取ります。Windows の GPU 計測が使えない環境では、利用可能な `nvidia-smi` を使って NVIDIA GPU を検出します。

取得できない値は `—` になります。CPU と GPU の使用率は、計測開始後に2回分のサンプルが集まると表示されます。

## English

Copy the extension folder into the WebUI's `extensions` directory and restart the WebUI. Open **Settings → Extensions → System Monitor** to choose the position, language, metrics, refresh interval and GPU. Click **Apply settings**. The generation panel displays the readings for `txt2img` and `img2img`.
