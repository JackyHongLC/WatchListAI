# WatchList AI

跨平台智慧播放清單與觀看進度整理工具。使用者可以貼上 YouTube、Netflix、動畫瘋、Bilibili、課程平台或自訂來源的影片資料，系統會整理成結構化清單，並提供排序、缺集偵測、重複檢查、觀看進度與匯出功能。

## 功能

- 多行文字輸入，一行一筆影片資料
- 支援平台、連結、片名、季數、集數與備註混合輸入
- 無 API Key 時可用規則解析
- 有 OpenAI API Key 時可啟用 AI 解析
- 自動排序、缺集偵測、重複提醒
- 可編輯觀看狀態
- 產生簡易觀看計畫
- 匯出 Markdown、CSV、JSON
- 可選背景圖片與背景音樂

## 素材

如需自訂背景或音樂，請把檔案放到 `assets` 資料夾：

```text
assets/
├─ background.jpg
└─ bgm.mp3
```

支援的背景圖檔名：

- `background.jpg`
- `background.jpeg`
- `background.png`
- `background.webp`

支援的音樂檔名：

- `bgm.mp3`
- `bgm.wav`
- `bgm.ogg`
- `music.mp3`

背景圖片會自動套用到頁面，背景音樂會出現在側邊欄播放器。瀏覽器通常會阻擋自動播放，所以目前採用使用者手動播放的方式。

## 安裝

```bash
pip install -r requirements.txt
```

## 執行

```bash
streamlit run app.py
```

## 設計說明

本工具不是影片下載器，也不假設 AI 一定能進入所有影片平台。Netflix、動畫瘋等平台可能需要登入、地區權限或會阻擋自動讀取，因此 WatchList AI 以使用者提供的片名、集數、連結與備註為主要依據。AI 模式主要用於清洗混亂輸入、推測欄位、分類與整理格式。
