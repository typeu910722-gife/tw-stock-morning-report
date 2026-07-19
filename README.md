# 台股晨報 V6.0

獨立的台股晨報系統，與其他品牌或專案無關。

## V6.0 功能

- 平日台灣時間 07:40 由 GitHub Actions 自動執行
- 自動產生最新台股晨報與手機版 PWA
- 自動部署到 GitHub Pages
- 自動把最新報告存回 Repository，保留最近 60 份歷史晨報
- TWSE 成交值排行三層備援：OpenAPI → MI_INDEX → 固定高流動性清單
- Android／iPhone 可加入主畫面，最近瀏覽內容可離線查看

## 第一次設定

1. 將全部檔案 Commit 並 Push 到 GitHub。
2. GitHub Repository 開啟 `Settings → Pages`。
3. `Build and deployment → Source` 選擇 `GitHub Actions`。
4. 到 `Actions → Stock Report → Run workflow` 手動執行一次。
5. 執行成功後，Pages 網址通常為：
   `https://你的帳號.github.io/tw-stock-morning-report/`

## 電腦本機執行

雙擊 `run_report.bat`，會產生：

- `outputs/.../台股日報_YYYYMMDD.html`
- `site/index.html`

## 手機安裝

- Android Chrome：開啟 Pages 網址，點網站上的「安裝」。
- iPhone Safari：分享 → 加入主畫面。

## 注意

GitHub 排程可能延遲數分鐘。若證交所資料來源暫時無回應，程式會切換備援來源，避免整份晨報中止。
