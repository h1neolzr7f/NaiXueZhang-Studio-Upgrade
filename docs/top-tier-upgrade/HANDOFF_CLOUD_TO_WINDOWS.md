# HANDOFF_CLOUD_TO_WINDOWS

## 1. Product and phase

Upgrade Nai学长工作室 to a first-tier NovelAI production OS. Current phase: **Phase 0 complete enough to continue Wave 2 on independent files**. Barrel lowest is 3.0 (img2img/inpaint canvas and ANR-dependent post). Do not claim top-tier.

## 2. Branches and SHAs

- Studio-Upgrade base: `main` `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`
- Integration: `cursor/cloud-top-tier-integration-f036` (continues `cursor/cloud-top-tier-integration-6d7e`)
- Manga-Editor-Desu-NAI: OUT_OF_SCOPE, not connected

## 3. Worker branches / PRs

This run keeps W0–W4 work on the integration branch and launches additional Cloud Worker agents for independent audits. Previous Upgrade PR #2 is historical continuation source. Pre-existing Upgrade PR #1 is unrelated.

## 4. Merged

Nothing merged to `main`.

## 5. Unmerged

This integration Draft PR: previous Phase 0 docs/tooling/Windows aliases plus this run's environment.json, NAI field reporting, tooling timeout/cancel, gallery micro-bench, fault injection, and Windows script static check.

## 6. Tests

- Cloud-safe pytest after this change (recorded in STATUS after the run)
- Sensitive scan
- `python scripts/bench_gallery.py --count 1000 --repeats 20`
- `python scripts/check_windows_scripts.py`

## 7. Cloud Build

Draft in progress: [bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274](https://cursor.com/dashboard/cloud-agents/builds/bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274)  
Personal transitional environment: [d93c0dbf-9877-11f1-ba66-0e7d0216e441](https://cursor.com/dashboard/cloud-agents/environments/e/d93c0dbf-9877-11f1-ba66-0e7d0216e441)  
Install baseline: `requirements.core.lock.txt` + pytest + langgraph + langgraph-checkpoint-sqlite + aiosqlite. No NAI token secret.

## 8. Migrations

None applied. v1.4→v1.5 data move remains a Windows item (WIN-014).

## 9. Public interface versions

WorkflowRequest / ErrorEnvelope / EventEnvelope / ToolSpec v1 in `butler/tooling`. Not wired to HTTP or LangGraph.  
NAI compile now also returns `requested_action`, `unsupported_fields`, `unknown_fields`. HTTP `action` remains `generate`.

## 10. Three shortest boards

1. `gen.img2img_inpaint_canvas` 3.0
2. `post.pipeline` 3.0
3. `assist.memory_tts_emotion` 4.0 (defer to v1.9; next implementable kernel is `assist.tool_loop` 5.0)

## 11. PENDING_LOCAL_WINDOWS

See PENDING_LOCAL_WINDOWS.md WIN-001..015.

## 12. Known bugs / gaps

- Official generate path is txt2img only; img2img/inpaint are reported, not compiled
- Studio UI has no cancel button
- `/app` gallery lacks drop-folder
- ANR path hardcoded to Windows personal directories
- Dual classic/`/app` UI drift
- Catalog vs gallery crawler tool dual definition
- Tooling kernel is not wired into `planning.py` / chat

## 13. Blockers

- Real NAI/Pixiv credentials
- Windows desktop verification

## 14. Windows install

1. Clone Upgrade and checkout `cursor/cloud-top-tier-integration-f036`
2. `powershell -File scripts/doctor_windows.ps1`
3. `powershell -File scripts/setup_windows.ps1`
4. Start with `一键启动.bat` or `START_GALLERY.bat`

## 15. First Windows test command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_tests_windows.ps1 -SkipBrowserTests
```

## 16. Recommended local topology

Lead + W1 NAI compile + W4 Windows verify. W2/W3 stay on independent files.

## 17. Rollback

`git checkout main` at `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`. Close the draft PR. Do not force-push.

## 18. Next

Continue Wave 2 on this branch. Do not start v1.6 UI/inpaint until compile tests lock current payload behavior. Do not integrate tooling into planning.py.

## 19. Still-running cloud agents

Lead `bc-6ecf51c6-e504-4cfe-85d6-9b8feaf5f036` is this run. Additional Cloud Workers may still be running; do not double-write leased files.
