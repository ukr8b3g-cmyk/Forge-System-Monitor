[English](#english)

# Forge System Monitor

Forge Neo、Forge Neo 2、reForge の生成画面に、CPU・RAM・GPU・VRAM・GPU 温度を表示する拡張です。RAM と VRAM は使用率と使用量／総量を表示します。

<img width="334" height="221" alt="生成画面のシステムモニター" src="https://github.com/user-attachments/assets/29b50cbc-1733-4ae6-a59c-a832fd31e3c2" />

## 導入

1. [リリース](https://github.com/ukr8b3g-cmyk/Forge-System-Monitor/releases/latest) から `Forge-System-Monitor.zip` をダウンロードして展開します。
2. 展開した `Forge-System-Monitor` フォルダーを WebUI の `extensions` にコピーします。
3. WebUI を再起動します。
4. 上部の **Settings** タブを開き、左メニューの **Extensions → System Monitor**（システムモニター）を選びます。

初期位置は `txt2img` と `img2img` の生成操作欄の下です。EasyPromptSelector がある場合はタグ選択の直下に表示されます。Compact UI では Generate の直下に配置します。

モニターの見出しをクリックすると計測値が折りたたまれます。もう一度クリックすると開きます。生成欄の下でもフローティングでも使えます。

## 設定

<img width="573" height="436" alt="システムモニターの設定画面" src="https://github.com/user-attachments/assets/aacc68a3-ad5b-4799-ab21-c7383fc964fa" />

| 設定 | 選択肢・動作 |
| --- | --- |
| モニターを表示 | モニターのオン・オフを切り替えます。既定はオンです。 |
| 表示位置 | 生成欄の下（既定）／フローティング。フローティングのときだけ四隅から固定位置を選べます。 |
| 表示言語 | `Auto`（既定）／`English`／`Japanese`。自動は WebUI のロケールに従い、日本語以外では英語を表示します。 |
| 監視する GPU | 自動または検出した GPU の機種名。自動は、GPU が1台ならその GPU、複数台なら WebUI の使用デバイスを識別できた場合にその GPU を表示します。 |
| 表示項目と更新 | CPU、RAM、GPU、VRAM、GPU 温度を個別に選択できます。更新間隔は1秒、2秒（既定）、5秒です。 |

変更は標準の **Apply settings** で反映します。全体をオフにしたときや、生成画面・ブラウザータブを離れたときは更新を止めます。表示言語の選択はモニター本体に適用されます。

## 計測

CPU と RAM は WebUI 環境に含まれる `psutil` で読み取ります。Windows では Windows の GPU カウンターから GPU 使用率と専用 VRAM を、ドライバーが提供する場合は GPU 温度も読み取ります。Windows の GPU 計測が使えない環境では、利用可能な `nvidia-smi` を使って NVIDIA GPU を検出します。

取得できない値は `—` になります。CPU と Windows の GPU 使用率は、計測開始後に2回分のサンプルが集まると表示されます。

---

## English

Forge System Monitor displays CPU usage, RAM usage, GPU usage, VRAM usage, and GPU temperature in the generation view of Forge Neo, Forge Neo 2, and reForge. RAM and VRAM readings show both the percentage and the amount used out of the total.

<img width="334" height="221" alt="System Monitor in the generation view" src="https://github.com/user-attachments/assets/29b50cbc-1733-4ae6-a59c-a832fd31e3c2" />

### Installation

1. Download `Forge-System-Monitor.zip` from the [latest release](https://github.com/ukr8b3g-cmyk/Forge-System-Monitor/releases/latest) and extract it.
2. Copy the extracted `Forge-System-Monitor` folder into the WebUI's `extensions` directory.
3. Restart the WebUI.
4. Open the **Settings** tab and select **Extensions → System Monitor** in the left menu.

By default, the monitor appears below the generation controls on `txt2img` and `img2img`. With EasyPromptSelector installed, it appears directly below the tag selector. In Compact UI, it appears below Generate.

Click the monitor heading to collapse the readings. Click it again to expand them. This works in both positions.

### Settings

<img width="573" height="436" alt="System Monitor settings" src="https://github.com/user-attachments/assets/aacc68a3-ad5b-4799-ab21-c7383fc964fa" />

| Setting | Options |
| --- | --- |
| Show monitor | Turns the monitor on or off. On by default. |
| Position | Below generation controls (default) or Floating. In Floating mode, use Corner to choose one of the four screen corners. |
| Monitor language | Auto (default), English, or Japanese. Auto follows the WebUI localization and falls back to English. |
| GPU to monitor | Choose Auto or a detected GPU by name. Auto selects the only available GPU, or the GPU used by the WebUI if it can be identified. |
| Metrics and refresh | Choose CPU, RAM, GPU, VRAM, and GPU temperature individually. The refresh intervals are 1, 2 (default), and 5 seconds. |

Click **Apply settings** to save your changes. Refreshing pauses when the monitor is off, when you leave the generation view, or when the browser tab is hidden. The language setting applies to the monitor.

### Measurements

The extension reads CPU and RAM data with the `psutil` package included in the WebUI environment. On Windows, it uses GPU performance counters for GPU usage and dedicated VRAM, and reads GPU temperature when the driver reports it. If Windows GPU measurements are unavailable, it uses `nvidia-smi` to detect NVIDIA GPUs when the command is available.

Unavailable values appear as `—`. CPU and Windows GPU usage appear after two samples have been collected.
