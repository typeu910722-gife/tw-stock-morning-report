# 台股晨報 V5.0

獨立的台股晨報 PWA。與映日所或其他品牌無關。

## 電腦執行

雙擊 `run_report.bat`。程式會同時產生：

- `outputs/.../台股日報_YYYYMMDD.html`
- `site/index.html` 手機 App 版入口

## 手機使用

1. 將專案 Push 到 GitHub。
2. 儲存庫進入 `Settings → Pages → Source → GitHub Actions`。
3. 進入 `Actions → Generate mobile stock report → Run workflow`。
4. 部署完成後開啟 GitHub Pages 網址。
5. Android Chrome 點網站上的「安裝」；iPhone Safari 點分享 → 加入主畫面。

## 自動更新

GitHub Actions 預設在台灣時間平日約 07:40 執行。GitHub 排程可能有幾分鐘延遲。

## V5.0

- 可安裝 PWA
- 今日晨報首頁
- 最近 60 份歷史晨報
- 離線快取最近瀏覽內容
- 手機底部導覽
- GitHub Actions 自動發布
