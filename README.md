# line-mac-reader

讀取 macOS 桌機版 LINE 未讀訊息的 CLI 工具：以 **UI 自動化（模擬點擊＋螢幕截圖）＋ OCR（預設 Apple Vision）** 掃描聊天清單中的未讀對話，讀取「上次讀取時間 → 現在」（無紀錄則近 48 小時）之間的訊息，輸出 JSON 檔與主控台摘要。

> **重要**：LINE 官方沒有可讀取個人聊天內容的 API。本工具本質上是「看畫面、認文字」，屬於**脆弱型自動化**——LINE 改版（版面、字體、badge 顏色）就可能失效，屆時需以診斷腳本重新校正 `config.yaml`。所有座標、色彩門檻、等待時間都集中在 config，程式碼不寫死。
>
> 本工具供個人自用，讀取的是自己帳號在自有裝置上可見的訊息。使用時請留意 LINE 服務條款與對話對象的隱私。

## 環境需求

- macOS（開發目標為 macOS 14/15；委託人首次執行後請在此補上實測版本）
- Python 3.11+
- 已安裝並**登入**的官方桌機版 LINE
- Homebrew（安裝 Tesseract 用）

## 安裝

```bash
# 1. Python 相依（含 Apple Vision 的 pyobjc binding）
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # 或 pip install -r requirements.txt

# 2. 建立自己的設定檔
cp config.example.yaml config.yaml

# （可選）備援 OCR 引擎 Tesseract——只有 config 設 ocr.engine: tesseract 才需要
brew install tesseract tesseract-lang
```

### OCR 引擎

預設使用 **Apple Vision framework**（macOS 內建的 `VNRecognizeTextRequest`）：繁中辨識準確度遠高於 Tesseract、速度快、免安裝任何引擎，且直接回傳每行文字的座標，訊息版面（左右氣泡、時間、日期分隔列）都由座標重建。Tesseract 保留為備援（`ocr.engine: tesseract`）。

**辨識率再提升的三道機制**（都在 `config.yaml` 的 `ocr` 區塊）：

1. **最新辨識模型**：固定使用 Vision Revision 3 並關閉逐圖語言自動偵測，強制 zh-Hant 優先。
2. **自訂詞彙 `custom_words`**：把常出現的人名、暱稱、行話列進去（例：`[郭毅驊, 出帳]`），Vision 的語言模型會偏向這些詞，罕見字人名的辨識率提升最明顯。對話名稱不用列——讀每個對話時會自動帶入。
3. **低信心二次辨識 `retry_below`**（預設 0.8）：整圖辨識後，信心低於門檻的行會裁出小圖、放大 `retry_upscale` 倍重跑一次，結果更有信心才採用（座標保持原位）。只補弱行，速度影響極小；設 0 可關閉。

## 系統權限（必要，缺一不可）

執行本工具的**終端機 App**（Terminal / iTerm2；若用其他方式啟動，則是對應的 Python 直譯器）需要兩項權限：

1. **螢幕錄製（Screen Recording）**——截圖必需
   「系統設定 → 隱私權與安全性 → 螢幕錄製」→ 開啟你的終端機 App → **重新啟動終端機**。
2. **輔助使用（Accessibility）**——模擬點擊、移動視窗必需
   「系統設定 → 隱私權與安全性 → 輔助使用」→ 開啟你的終端機 App。

程式啟動時會自我檢查這兩項權限，缺少時會印出明確錯誤訊息並中止（不會截到全黑畫面或點擊無效卻繼續跑）。

## 首次使用：校正流程（必做）

badge 偵測是整條流程風險最高的一環，請先跑診斷腳本確認：

```bash
python scripts/diagnose_badges.py --config config.yaml
```

腳本會啟動 LINE、固定視窗位置，並在 `debug/diagnose_<時間>/` 輸出：

| 檔案 | 用途 |
|---|---|
| `fullwindow.png` | 整個 LINE 視窗，畫出 `chat_list` / `messages` / `chat_title` 三個區域框 —— **先確認這三個框有對齊**，沒對齊就調 `config.yaml` 的 `regions` |
| `chatlist.png` | 聊天清單區域原始截圖 |
| `mask.png` | 未讀 badge 的 HSV 遮罩（白色 = 命中）|
| `annotated.png` | 綠框 = 偵測到的 badge，藍框 = 推得的列範圍，**黃色十字 = 實際會點擊的位置**——十字沒落在正確的人身上就是座標要校正 |

若 badge 沒被抓到，用 `--sample X,Y` 取 badge 的 HSV 值（座標對照 `chatlist.png` 的像素位置），再回填 `badge.hsv_lower` / `hsv_upper`：

```bash
python scripts/diagnose_badges.py --config config.yaml --sample 250,120
```

## 使用

```bash
# 標準執行：掃描所有未讀對話並輸出
line-mac-reader --config config.yaml

# 讀取「任何」對話（不限未讀）
line-mac-reader --config config.yaml --chat "王小明"              # 用 LINE 搜尋框開啟指定對話並讀取
line-mac-reader --config config.yaml --chat "王小明" --chat "家人群"  # 可重複指定多個
line-mac-reader --config config.yaml --all                       # 讀取清單目前「可見」的每一列

# 常用旗標
line-mac-reader --config config.yaml --only "王小明"     # 只處理名稱含關鍵字的對話（測試用）
line-mac-reader --config config.yaml --dry-run          # 讀取但不更新 last_read 狀態
line-mac-reader --config config.yaml --fallback-hours 24 # 無紀錄時改讀近 24 小時
line-mac-reader --config config.yaml --debug            # 保存每步截圖到 debug/
line-mac-reader --config config.yaml --out /path/to/dir # 指定輸出目錄
line-mac-reader --reset                                  # 清空所有 last_read 狀態
```

執行期間 **LINE 視窗必須維持在前景、不可被遮擋、不要動滑鼠鍵盤**。

### 三種讀取範圍

| 模式 | 行為 | 注意事項 |
|---|---|---|
| （預設） | 只讀有未讀 badge 的對話 | badge 偵測需先校正 |
| `--chat "名稱"` | 用 LINE 搜尋框搜尋，OCR 搜尋結果找到**名稱相符的那一列**再點開，**不管有無未讀**；可重複指定 | 名稱要能被 LINE 搜尋命中；透過剪貼簿貼上（會覆蓋剪貼簿內容）。搜尋框位置在 `config.yaml` 的 `regions.search_box`，可用診斷腳本確認（粉紅框） |
| `--all` | 逐頁捲動聊天清單，讀取**每一列** | 頁數上限 `scroll.max_list_pages`（預設 8，捲到底自動停）；列高依 `regions.row_height` 切格；對話身分以開啟後的標題欄為準並據此去重 |

三種模式讀完都會更新該對話的 `last_read`（`--dry-run` 除外），所以用 `--chat`/`--all` 讀過的對話，下次預設模式只會接著讀新訊息。

**防讀錯人**：無論哪種模式，點開對話後都會先 OCR 標題欄與目標名稱做模糊比對（去空白、雙向包含），不符就跳過該對話並在 JSON 的 `error` 記錄原因，不會把別人的訊息讀進來。

### 輸出

1. **主控台摘要**：每個未讀對話一段（名稱、讀取區間、訊息則數、逐則內容）。
2. **JSON 檔**：`output/YYYYMMDD_HHMMSS.json`：

```json
{
  "run_at": "2026-07-02T14:30:00+08:00",
  "chats": [
    {
      "chat_name": "王小明",
      "chat_type": "unknown",
      "read_from": "2026-07-01T09:12:00+08:00",
      "read_from_source": "last_read",
      "read_to": "2026-07-02T14:30:00+08:00",
      "error": null,
      "messages": [
        {
          "sender": "王小明",
          "timestamp_est": "2026-07-02T10:05:00+08:00",
          "timestamp_confidence": "high",
          "text": "明天的會議改到下午三點",
          "kind": "text",
          "ocr_confidence": 0.97
        }
      ]
    }
  ]
}
```

- `read_from_source`：`last_read`（上次讀取紀錄）或 `fallback_48h`（無紀錄，往前推 48 小時滾動視窗）。
- `timestamp_confidence: low` 表示日期是推估的（見下方限制）。
- `ocr_confidence` 低於 `config.yaml` 的 `ocr.min_confidence` 時，摘要會標 `[OCR低信心]`，建議人工複核。
- 時區固定 `Asia/Taipei`（config 可改）。

### 狀態管理

每個對話成功讀完後，`state.sqlite3` 會把該對話的 `last_read_at` 更新為本次 `run_at`；下次執行只讀這之後的訊息。`--dry-run` 不更新、`--reset` 清空。狀態鍵是 **OCR 到的對話名稱**（風險見下）。

## 每日自動摘要到 Slack（客戶討論 → 隔天早上待辦提點）

工作流：每天早上排程自動執行 → 讀取所有未讀對話（官方帳號黑名單先剔除）→ 存 JSON（`output/` 就是完整存檔）→ 把摘要推到 Slack Incoming Webhook，含「待辦候選」置頂區（訊息含「請/合約/報價/確認…」等關鍵字者，關鍵字在 config 可調）。

### 設定步驟

1. **config.yaml** 填 webhook 與黑名單：

```yaml
slack:
  webhook_url: https://hooks.slack.com/services/T000/B000/XXXX
filters:
  exclude_chats: [官方帳號, 客服, LINE Pay]   # 名稱含這些字串的對話一律跳過
```

2. **手動測一次**（`--slack-webhook` 也可直接帶 URL 蓋過 config）：

```bash
line-mac-reader --config config.yaml --slack
```

3. **裝排程**（launchd，macOS 原生）：

```bash
# 編輯 launchd/com.linemacreader.daily.plist：
#   把 /Users/YOURNAME/macos-line-reader 換成實際路徑、調整執行時間（預設 08:30）
cp launchd/com.linemacreader.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.linemacreader.daily.plist
launchctl start com.linemacreader.daily     # 立即手動觸發測試
```

### 排程的前提（重要）

- 觸發當下 Mac 必須**醒著、已登入解鎖**，LINE 已登入——建議把時間設在你固定在電腦前的時段；執行的一兩分鐘內 LINE 會被帶到前景，勿操作滑鼠鍵盤。
- 第一次由 launchd 觸發時，macOS 可能對 venv 裡的 Python 重新跳「螢幕錄製／輔助使用」權限視窗，允許一次即可。
- 每天讀取範圍自動銜接：狀態庫記錄每個對話的上次讀取時間，隔天只讀新訊息。
- 執行紀錄在專案目錄的 `launchd.out.log` / `launchd.err.log`。
- 摘要（含訊息內容）會送到你的 Slack workspace——webhook URL 等同這個頻道的投遞權限，請妥善保管，也留意客戶對話內容進 Slack 是否符合你與客戶的保密約定。

## 運作原理（模組導覽）

```
src/line_mac_reader/
├─ main.py             # CLI、流程編排、JSON/摘要輸出、單一對話失敗不中斷整體
├─ permissions.py      # 螢幕錄製 / 輔助使用權限自檢
├─ line_controller.py  # open -a LINE、帶前景、固定視窗位置與大小
├─ screen.py           # mss 截圖；Retina 座標換算集中於 Scaler（有單元測試）
├─ chatlist.py         # 未讀 badge HSV 色彩遮罩＋輪廓偵測 → 列座標 → OCR 對話名稱
├─ reader.py           # 開啟的對話：快速連拍捲動→批次整圖 OCR→版面重建→時間戳→去重
├─ ocr.py              # OCR 統一介面：Apple Vision（預設）/ Tesseract（備援）
├─ state.py            # SQLite：chat_key → last_read_at
├─ models.py           # dataclass：Rect / UnreadChat / Message / ChatResult
└─ utils_time.py       # 日期分隔列解析、HH:MM 補全、Asia/Taipei 時區
```

**Retina 注意**：`mss` 截圖是實體像素、`pyautogui` 點擊用邏輯座標（Retina 下差 2 倍）。所有換算集中在 `screen` 模組，其他模組一律不得自行乘除比例。另有一個已修復的陷阱：macOS 上 `mss` 會把截圖**寬度補到 16 的倍數**，多出的欄位是區域右側的真實畫面內容——倍率一律以「高度」推算並裁掉補寬，否則點擊座標會系統性偏上（越下面的列偏越多）。

**捲動**：預設 `scroll.mode: pixel`，用原生 CGEvent 像素捲動，一步捲 `page_fraction`（預設 0.75）個訊息區高度，比滾輪格數快一個數量級；保留 25% 重疊供跨截圖去重合併。若像素捲動在你的環境行為異常，可退回 `mode: wheel`。

**兩階段讀取（速度關鍵）**：讀對話時先**快速連拍**——捲動與截圖之間只等 UI 重繪（`timing.scroll_wait`，預設 0.35s），期間不做 OCR，只每 `scroll.cutoff_check_every` 張抽查一次「是否已捲過 cutoff」；捲完後再對每張截圖做**一次整圖 OCR**，用回傳的文字座標重建版面（左緣位置分左右氣泡、垂直間距切氣泡、置中短行判日期分隔列、「已讀」標籤剔除、獨立的「上午/下午 H:MM」行依垂直距離掛回氣泡）。

**時間戳重建**：LINE 每則訊息只顯示 `HH:MM`（含上午/下午格式），日期來自畫面中的日期分隔列（「2026年7月1日」「昨天」「今天」等）。由上而下維護「目前日期上下文」把 `HH:MM` 補成完整時間；無法確定日期者標 `timestamp_confidence: low`。cutoff 比對刻意從寬——寧可多讀也不漏，重疊由去重（發送者＋文字內容）處理。

## 已知限制與風險

1. **LINE 改版**（版面、字體、badge 顏色）會使偵測失效；用診斷腳本重新校正 `config.yaml`。
2. 只讀得到**畫面上顯示**的內容：貼圖／圖片／影片只能標成 `[貼圖]`/`[圖片]` 占位（且偵測是 best-effort），被摺疊的訊息拿不到。
3. **時間戳為推估值**：跨日、跨年、系統語系非繁中都可能影響解析；`low` 信心的時間請自行斟酌。
4. **對話名稱作為狀態鍵**：名稱重複或過長被截斷時，last_read 紀錄可能互相覆蓋。
5. OCR 對表情符號、特殊排版可能誤判；純貼圖/圖片訊息（畫面上沒有任何文字）OCR 不到會**整則漏掉**。版面判斷的門檻（`layout.side_ratio`、`bubble_gap` 等）可在 config 調整。
6. 群組訊息的**發送者辨識為啟發式**（氣泡上方字級較小的短行才視為人名），仍可能誤判。
7. 需要系統層級權限；執行時 LINE 視窗必須前景、不可遮擋，期間請勿使用滑鼠鍵盤。
8. 未讀掃描與 `--all` 會**逐頁往下捲動聊天清單**（先回到頂端，每頁處理完往下捲約 3/4 頁，捲到底或達 `scroll.max_list_pages` 為止；跨頁重疊以開啟後的標題去重）。要涵蓋更多對話就調大 `max_list_pages`。
9. **聊天清單底部的廣告橫幅**：`regions.list_bottom_exclude`（預設 110）把清單底部劃為保留區，永不點擊（誤點廣告會開瀏覽器、把 LINE 擠出前景）。診斷圖會以紅框標出保留區；另外每次開對話前都會先把 LINE 重新帶回前景，就算焦點被搶走也能自動恢復。

## 開發

```bash
pip install pytest
python3 -m pytest tests/        # 純邏輯測試（座標換算、時間重建、切塊、去重、狀態），Linux/CI 也能跑
```

macOS 專屬相依（pyobjc、mss、pyautogui、opencv）都是延遲載入，單元測試不需要它們。

### 里程碑對照（SOW §10）

- **M1** 權限自檢、啟動帶前景、截圖、Retina 換算＋測試 ✅
- **M2** badge 偵測診斷腳本（`scripts/diagnose_badges.py`）✅ —— *需委託人在實機校正 config*
- **M3** 單對話讀取（`--only`）：捲動＋OCR＋時間戳重建＋去重 ✅
- **M4** SQLite 狀態、last_read／48h fallback、`--dry-run`/`--reset` ✅
- **M5** 整體編排、JSON 輸出、錯誤容錯、README ✅
