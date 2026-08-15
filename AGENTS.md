# Agent operating rules (A-layer)

This file is the short always-on extract of the Studio-only top-tier upgrade spec. It does not replace `docs/top-tier-upgrade/`.

## Product

Nai学长工作室 is a NovelAI production OS for high-volume creators. The only in-scope repository is `h1neolzr7f/NaiXueZhang-Studio-Upgrade`. `Manga-Editor-Desu-NAI` is OUT_OF_SCOPE.

## Hard boundaries

1. Do not rewrite the existing Studio or replace LangGraph durable workflows.
2. Do not delete SQLite tasks, events, receipts, audit, or restart recovery.
3. Chat Tool Loop must never execute generate, crawl, delete, publish, or other side effects. Those actions only create a confirmation ticket for LangGraph.
4. Do not copy AGPL code (LingChat, Semi-Auto-NovelAI-to-Pixiv) into this MIT tree.
5. Do not start with God Agent, key/mouse hooks, screen capture, or arbitrary plugins.
6. Advance Phase 0 → v1.6 → v1.7 → v1.8 → v1.9. Do not skip a failed gate.
7. Do not claim a capability complete without tests, benchmarks, and Lead review.
8. Do not weaken idempotency, approval, unknown isolation, redaction, or one-click start.
9. Do not merge or force-push `main`, change LICENSE, publish a Release, or use real NAI tokens for unpaid/unlimited generation.
10. Read source before changing it. Do not invent a second NovelAI client, task store, gallery index, or permission system.

## Ownership

Lead owns `butler/store.py`, `butler/workflow_runtime.py`, `butler/planning.py`, `butler/agents.py`, `data/butler_catalog.json`, public migrations, and license/release files. See `docs/top-tier-upgrade/OWNERSHIP.md`.

## Commands

```powershell
python -m pip install -r requirements.core.lock.txt pytest langgraph langgraph-checkpoint-sqlite
python -m compileall -q -x "runtime|\.venv|node_modules|data" .
python -m pytest -q --ignore=tests/test_pixiv_selector_probe.py
python scripts/scan_sensitive.py --git-candidates --content-only
```

Windows full verification: `scripts/verify.ps1` or `scripts/run_tests_windows.ps1`.
Windows diagnosis: `scripts/doctor_windows.ps1`.
