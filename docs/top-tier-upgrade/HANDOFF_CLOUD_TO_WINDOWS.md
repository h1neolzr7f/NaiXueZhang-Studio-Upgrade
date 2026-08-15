# HANDOFF_CLOUD_TO_WINDOWS

## 1. Product and phase

Upgrade Nai学长工作室 to a first-tier NovelAI production OS. Current phase: **Phase 0 complete enough to continue Wave 2 on independent files**. Barrel lowest is 3.0 (img2img/inpaint canvas and ANR-dependent post). Do not claim top-tier.

## 2. Branches and SHAs

- Studio-Upgrade base: `main` `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`
- Integration: `cursor/cloud-top-tier-integration-6d7e` @ `35e7d3c1aafa98e1ca81f1e44c7bad750e9c839d` (GitHub MCP head; local clone SHA differs)
- Frozen v1.4 Studio: `6d0298495d3086d9ba6e9c47b9cde91b65e994b0` — do not modify

## 3. Worker branches / PRs

This run used in-process explore agents (W0–W4) plus Lead commits on the integration branch. No separate worker Draft PRs yet. Pre-existing Upgrade PR #1 is unrelated.

## 4. Merged

Nothing merged to `main`.

## 5. Unmerged

This integration Draft PR: Phase 0 docs, AGENTS.md, POSIX skips (D-003/D-007), doctor/setup/test/build Windows aliases, `butler/tooling` skeleton, expanded NAI compile lock tests. Git push from the v1.4-bound Cloud workspace is 403; publication uses GitHub MCP.

## 6. Tests

- Critical cloud subset: 119 passed, 3 skipped
- Sensitive scan clean
- Quality gate P0=0, existing P1 Regression Guard
- Tooling and compile-lock tests added on this branch

## 7. Cloud Build

BLOCKED. This Cloud run's environment.repos is `github.com/h1neolzr7f/NaiXueZhang-Studio`. A reusable Upgrade build must be created from an agent bound to Studio-Upgrade.

## 8. Migrations

None applied. v1.4→v1.5 data move remains a Windows item (WIN-014).

## 9. Public interface versions

WorkflowRequest / ErrorEnvelope / EventEnvelope / ToolSpec v1 in `butler/tooling`. Not wired to HTTP or LangGraph.

## 10. Three shortest boards

1. `gen.img2img_inpaint_canvas` 3.0
2. `post.pipeline` 3.0
3. `assist.memory_tts_emotion` 4.0 (defer to v1.9; next implementable kernel is `assist.tool_loop` 4.5)

## 11. PENDING_LOCAL_WINDOWS

See PENDING_LOCAL_WINDOWS.md WIN-001..015.

## 12. Known bugs / gaps

- Official generate path is txt2img only
- Studio UI has no cancel button
- `/app` gallery lacks drop-folder
- ANR path hardcoded to Windows personal directories
- Dual classic/`/app` UI drift
- Catalog vs gallery crawler tool dual definition

## 13. Blockers

- Upgrade Cloud Build needs a new agent on the Upgrade repo
- Real NAI/Pixiv credentials
- Windows desktop verification

## 14. Windows install

1. Clone Upgrade and checkout the integration branch
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

Lead `bc-e2ee9110-0402-4570-a6d2-8e8168a76d7e` is this run. Explore workers completed. No other Upgrade writers.
