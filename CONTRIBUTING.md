# 貢獻指南

## GUI 暫行規則

凡 PR 涉及 `gui` stage、`[gui]` 設定，或需要桌面視窗的場景或工具，都必須附上人工驗證截圖或錄影才能合併。畫面須顯示 Isaac Sim 視窗已成功開啟，且場景已載入。請附上實際執行的指令，驗證環境只填「電腦規格」或「test_1 server」。

## Xvfb 實驗結果

實驗使用與本專案 `gui` stage 內容相同的映像（`FROM devel`，只加上 `ENV`），在 RTX 5090 上執行 Isaac Sim 6.2.0-rc.15。Xvfb 啟用 GLX，畫面設定為 `1920x1080x24`。

有視窗與 `--no-window` 兩種情境各執行一次。兩次 Kit 都成功啟動，選單、Stage 與 Viewport 均已就緒。整個視窗截圖的非黑像素比例均約為 0.61，透過 `menu_click_with_retry` 點選 Create → Shape → Cube 也都成功。有視窗的那次，`xwininfo` 顯示視窗標題為 `Isaac Sim Full 6.2.0 - New Stage*`，大小為 1440×900。

兩次日誌都沒有出現 `Failed to initialize graphics environment`。日誌中的 Error 行與未掛載快取目錄有關：Kit 的 data 與 documents 目錄建立失敗，`omni.simready.content.browser` 載入失敗。這些錯誤未影響 Kit 啟動。

可行的自動化流程是在 Xvfb 下啟動 Kit，等選單、Stage 與 Viewport 就緒且場景載入完成，再呼叫 `capture_app_screenshot_async` 截圖。固定等待若干影格無法確認載入進度。此流程尚未納入 CI，仍須驗證參考截圖（golden）在不同 GPU 型號間的穩定性、流程在 CI runner 上的實跑結果，以及自家 extension 的 UI。詳細實驗紀錄與重跑腳本位於本機 `isaac_ws` 工作區的 `experiments/gui_test/`。
