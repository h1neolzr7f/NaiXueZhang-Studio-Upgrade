# HANDOFF_CLOUD_TO_WINDOWS

## 1. Product and phase

Upgrade Nai学长工作室 to a first-tier NovelAI production OS. Current phase: **cloud-completable v1.6–v1.8 landed**. Barrel lowest core is 4.0 (`assist.memory_tts_emotion`, v1.9 deferred). Next implementable lowest is 6.0 (img2img compile without Studio canvas). Do not claim top-tier.

## 2. Branches and SHAs

- Studio-Upgrade base: `main` `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`
- Integration: `cursor/cloud-top-tier-integration-f036` @ `76a8c6162cdde8af24d458b2b5663b7890323ab9` (continues `cursor/cloud-top-tier-integration-6d7e`)
- Manga-Editor-Desu-NAI: OUT_OF_SCOPE, not connected

## 3. Worker branches / PRs

This run keeps W0–W4 work on the integration branch and launches additional Cloud Worker agents for independent audits. Previous Upgrade PR #2 is historical continuation source. Pre-existing Upgrade PR #1 is unrelated.

## 4. Merged

Nothing merged to `main`.

## 5. Unmerged

This integration Draft PR: previous Phase 0 docs/tooling/Windows aliases plus this run's environment.json, NAI field reporting, tooling timeout/cancel, gallery micro-bench, fault injection, and Windows script static check.

## 6. Tests

- Cloud pytest: 1132 passed, 68 skipped, 1 pre-existing P1 quality-gate failure
- Sensitive scan clean
- `python scripts/bench_gallery.py --count 1000 --repeats 20` (hits=200, synthetic)
- `python scripts/check_windows_scripts.py` passed

## 7. Cloud Build

READY: [bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274](https://cursor.com/dashboard/cloud-agents/builds/bld-20260815-c10799be-3d0d-41bd-8535-6eaedb553274)  
Personal transitional environment: [d93c0dbf-9877-11f1-ba66-0e7d0216e441](https://cursor.com/dashboard/cloud-agents/environments/e/d93c0dbf-9877-11f1-ba66-0e7d0216e441)  
Install baseline: `requirements.core.lock.txt` + pytest + langgraph + langgraph-checkpoint-sqlite + aiosqlite. No NAI token secret.

## 8. Migrations

None applied. v1.4→v1.5 data move remains a Windows item (WIN-014).

## 9. Public interface versions

WorkflowRequest / ErrorEnvelope / EventEnvelope / ToolSpec v1 in `butler/tooling`. Not wired to HTTP or LangGraph.  
NAI compile returns `requested_action`, `unsupported_fields`, `unknown_fields`. HTTP `action` is `generate` unless D-012 img2img/infill rules are met. Gallery additive index lives in the same SQLite file. Tooling kernel is still not wired to `planning.py`.

## 10. Three shortest boards

1. `assist.memory_tts_emotion` 4.0 (defer to v1.9)
2. `gen.img2img_inpaint_canvas` 6.0 (compile yes, Studio canvas no)
3. `assist.tool_loop` 6.0 (kernel expanded, not wired to chat)

`post.pipeline` is 6.0. Pixiv account work is deferred this wave.

## 11. PENDING_LOCAL_WINDOWS

See PENDING_LOCAL_WINDOWS.md WIN-001..015.

## 12. Known bugs / gaps

- Official generate path compiles img2img/infill; Studio has no mask canvas
- Studio UI has no cancel button
- `/app` gallery lacks drop-folder
- ANR path hardcoded to Windows personal directories
- Dual classic/`/app` UI drift
- Catalog vs gallery crawler tool dual definition
- Tooling kernel is not wired into `planning.py` / chat
- Gallery similar/dup is library-only; no additive HTTP routes this wave

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

Cloud compile/index/kernel work is in. Next local work: Windows WIN-* plus Studio img2img canvas. Do not integrate tooling into planning.py until a Lead review of this wave. Do not merge main.

## 19. Still-running cloud agents

Lead `bc-6ecf51c6-e504-4cfe-85d6-9b8feaf5f036` is this run. Additional Cloud Workers may still be running; do not double-write leased files.
