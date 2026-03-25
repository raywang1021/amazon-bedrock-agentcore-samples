---
inclusion: manual
---

# Code Review Steering

When the user requests a code review:

1. First, read all existing code review files in `.kiro/` (files matching `code-review-*.md`) to understand previous findings and their status (fixed, deferred, open).
2. Perform the review, focusing on new changes since the last review.
3. Save the review result to `.kiro/code-review-YYYYMMDD.md` with today's date.
4. Mark items from previous reviews as FIXED, DEFERRED, or STILL OPEN.
5. Do NOT create review files outside `.kiro/` — they are internal-only.

Review files in `.kiro/` are excluded from git (via `.gitignore`) and should never be pushed to the repository.
