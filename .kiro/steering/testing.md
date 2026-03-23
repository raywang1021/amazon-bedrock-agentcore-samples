---
inclusion: auto
---

# 自驗規則

所有修改做完之後，必須自行驗證，人只是進行「verify」，不是主測試者。

1. 跑既有測試：`python -m pytest test/unit/` 確認沒有 regression
2. 用 `getDiagnostics` 檢查所有修改過的檔案
3. 新邏輯要 smoke test（不要假設能動就不測）
4. 回報驗證結果，失敗的話先修再繼續
