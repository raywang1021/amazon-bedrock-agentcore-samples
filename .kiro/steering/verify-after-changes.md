---
inclusion: auto
---

# Self-Verification After Changes

After developing a new feature, adjusting existing functionality, or fixing a bug, you MUST self-verify your changes before considering the task complete:

1. **Run existing tests**: If there are relevant test files under `test/`, run them with `python -m pytest` to confirm nothing is broken.
2. **Check diagnostics**: Use `getDiagnostics` on all modified files to catch syntax, type, or lint issues.
3. **Smoke test new code**: If you added new logic (e.g., a new tool, a sanitization function), write or run a quick verification to confirm it works — don't just assume.
4. **Report results**: Tell the user what you verified and whether it passed or failed. If tests fail, fix them before moving on.

Do not skip verification even if the change looks trivial.
