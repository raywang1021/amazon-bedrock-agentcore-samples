---
inclusion: auto
---

# Git Push 規則

當執行 git push 時，必須推送到兩個 remote：

1. 先推 GitHub：`git push origin <branch>`
2. 再推 GitLab：`git push gitlab <branch>`

兩個都要成功才算完成。如果 GitLab push 因為 SSH passphrase 失敗，提醒使用者手動執行。
