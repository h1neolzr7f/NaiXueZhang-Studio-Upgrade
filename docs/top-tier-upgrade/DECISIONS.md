# Decisions

## D-001 Bind implementation to Studio-Upgrade

- Date: 2026-08-15
- Capability: execution scope
- Existing behavior: This Cloud run started on `h1neolzr7f/NaiXueZhang-Studio` (frozen v1.4, SHA `6d0298495d3086d9ba6e9c47b9cde91b65e994b0`).
- Options: upgrade the frozen v1.4 repo; stop; execute on `NaiXueZhang-Studio-Upgrade`.
- Chosen: execute on Upgrade @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`. Do not change v1.4 default branch.
- Evidence: Upgrade README/CONTRIBUTING call it the v1.5+ trunk; spec unique target; butler/agents.py exists only there.
- Risks: this Cloud Environment cannot snapshot Upgrade for future agents.
- Tests: none
- Rollback: leave v1.4 untouched
- Layer: B (repo binding), A (do not treat Manga or v1.4 freeze as upgrade trunk)

## D-002 Branch names

- Date: 2026-08-15
- Chosen: `cursor/cloud-top-tier-integration-6d7e` maps to spec `cloud/top-tier-integration`. Worker names map the same way.
- Layer: C

## D-003 POSIX skip for Windows-shell tests

- Date: 2026-08-15
- Existing behavior: `test_startup_safety`, `test_release_script_safety`, `test_plaintext_at_rest` call cmd/powershell/DPAPI and fail on Linux.
- Chosen: skip those cases unless `os.name == "nt"`. Keep static string and Python process-guard tests.
- Evidence: W4 audit; first cloud pytest stopped on venv start test.
- Tests: the skipped tests still run on GitHub `windows-latest`.
- Rollback: revert the skip helpers
- Layer: B

## D-004 Frozen public interfaces (Wave 1)

- Date: 2026-08-15
- ToolSpec / ErrorEnvelope / EventEnvelope / WorkflowRequest: see `butler/tooling/`
- NAI: keep `nai_api.generate_image` as the only generate HTTP client. Compile via `nai_char.build_generate_payload`.
- Gallery: keep `WorkRef={gallery_id,work_id}` and existing `/api/ai_works_search` JSON. New dup/similar/album routes are additive.
- InteractiveAgentRuntime may only emit WorkflowRequest for confirm/cost/destructive.
- Layer: A for safety, B for type layout

## D-005 Windows script aliases

- Date: 2026-08-15
- Chosen: add `doctor_windows.ps1` (new). `setup_windows.ps1`, `run_tests_windows.ps1`, `build_windows.ps1` are thin aliases over INSTALL.bat / verify.ps1 / make_release.ps1.
- Layer: C

## D-006 Manga and Phone repos

- Date: 2026-08-15
- Chosen: `Manga-Editor-Desu-NAI` and `NaiXueZhang-Studio-Phone` are OUT_OF_SCOPE / SUPERSEDED_OUT_OF_SCOPE for this plan.
- Layer: A

## D-007 Additional POSIX skips for DPAPI and cmd.exe writers

- Date: 2026-08-15
- Existing behavior: Linux cloud pytest fails when tests call `protect_secret` or `cmd.exe`.
- Chosen: skip those persistence/cmd cases unless `os.name == "nt"`. Do not change production encryption or quota semantics to go green on Linux.
- Tests: architecture token writes, Pixiv account restore/import/migrate, crawler case-insensitive ownership, runtime selector cmd probe.
- Layer: B

## D-008 Continue on a new Upgrade-bound integration branch

- Date: 2026-08-15
- Existing behavior: Previous work lived on `cursor/cloud-top-tier-integration-6d7e` because that Cloud run was bound to frozen v1.4.
- Chosen: this run continues that tree as `cursor/cloud-top-tier-integration-f036` on Upgrade. Do not redo Phase 0. Do not modify `main`.
- Evidence: this run's `environment-info.repos` is `github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade`.
- Tests: existing Phase 0 tests plus this wave's compile/tooling/bench/fault tests
- Rollback: delete the new branch; leave PR #2 as historical
- Layer: C for branch name, B for continuation

## D-009 Report uncompiled NAI fields instead of changing HTTP action

- Date: 2026-08-15
- Capability: gen.img2img_inpaint_canvas / restore.png_stealth_v4
- Existing behavior: `build_generate_payload` always emits `action=generate` and omits `image`/`mask`.
- Options: silently start img2img; add a second client; report requested/unsupported/unknown fields and keep HTTP generate.
- Chosen: keep HTTP `action=generate`. Add `requested_action`, `unsupported_fields`, `unknown_fields`.
- Evidence: `tests/test_nai_generate_compile.py` already locks txt2img until img2img lands; changing action would be a production behavior change before Phase 0/v1.6 UI exists.
- Tests: `test_unknown_and_uncompiled_fields_are_reported_not_dropped`
- Rollback: revert the extra return keys
- Layer: B

## D-010 Missing ANR must not fail Lanczos upscale

- Date: 2026-08-15
- Capability: post.pipeline
- Existing behavior: mosaic enabled + no ANR raised and aborted the whole pipeline after upscale work.
- Chosen: skip mosaic as `mosaic:unavailable`, keep `upscale:2x`, record `upscale_engine=lanczos`, continue metadata.
- Evidence: W0 review; `tests/test_post_pipeline.py::PostPipelineAnrOptionalTests`
- Tests: missing ANR still writes `_up2x` and `_final`
- Rollback: restore the RuntimeError on `mosaic_runtime_status.ok is False`
- Layer: B

## D-011 Skip account/Pixiv path this wave

- Date: 2026-08-15
- Capability: publish.pixiv_browser / credentials
- Existing behavior: CRED-001 blocked on real NAI/Pixiv verification.
- Chosen: user said Pixiv is not urgent and to continue the upgrade without account work. Do not persist any chat-provided token. Do not run paid NovelAI generation. Do not implement Pixiv login this wave.
- Evidence: user instruction this turn
- Tests: none
- Rollback: n/a
- Layer: B (scope), A (do not commit secrets or unpaid generation)

## D-012 Compile img2img / infill on the existing client

- Date: 2026-08-15
- Capability: gen.img2img_inpaint_canvas
- Existing behavior: D-009 reported `requested_action` / `unsupported_fields` and kept HTTP `action=generate`.
- Options: keep reporting-only; add a second client; compile on `nai_char.build_generate_payload` / `nai_api.generate_image`.
- Chosen: compile on the existing client. Precise Reference stays `generate`. A lone `image` without an explicit img2img/inpaint request stays `generate` and is listed in `unsupported_fields`. Explicit `img2img` + `image` → HTTP `img2img`. `mask`+`image`, or explicit inpaint/infill + `image` → HTTP `infill`. Vibe keys stay unsupported. No paid NovelAI call.
- Evidence: `tests/test_nai_generate_compile.py`, `tests/test_nai_param_snapshots.py`
- Tests: those files plus `tests/test_nai_png_restore.py`
- Rollback: revert `nai_char_modules/generation.py` and the lock tests
- Layer: B (supersedes D-009 HTTP freeze once compile rules are met)

## D-013 Additive gallery index, no second store

- Date: 2026-08-15
- Capability: search.fts_works_prompt / search.visual_similar
- Existing behavior: design-only `GALLERY_INDEX_DESIGN.md`; production search still full `rebuild_fts`.
- Chosen: add `gallery_index.py` tables in the existing per-gallery SQLite. Dirty-set incremental FTS via existing `_sync_*`. Exact sha256 groups and local dHash/pHash similar. No butler task DB. No `/api/ai_works_search` JSON change. No HTTP routes this wave (library + `Database.incremental_index` only). Embed stays `local_none`.
- Evidence: `tests/test_gallery_index.py`
- Tests: dirty predicate, incremental skip, exact/near/similar, Database hook
- Rollback: stop calling `incremental_index`; `DROP TABLE` of the two new tables
- Layer: B

## D-014 Expand tooling kernel without planning.py

- Date: 2026-08-15
- Capability: assist.tool_loop
- Existing behavior: kernel exists; chat/planner not wired.
- Chosen: add `compile_nai_preview` and `gallery_index_preview` as kernel-only read tools. Add keyed idempotency and output-schema checks on the executor. Do not import tooling from `butler/planning.py`. Cost/destructive tools still only emit WorkflowRequest.
- Evidence: `tests/tooling/test_kernel_tools.py`
- Tests: compile preview, idempotency, in-memory dups, planning import lock
- Rollback: revert `butler/tooling/kernel_tools.py` and executor cache
- Layer: B

## D-015 Additive gallery index HTTP

- Date: 2026-08-15
- Capability: search.fts_works_prompt / search.visual_similar
- Existing behavior: D-013 library only, no HTTP.
- Chosen: add the four reserved routes. Do not change `/api/ai_works_search` JSON. Incremental entry is `gallery_index.run_incremental` so `db.py` stays ≤1000 lines.
- Evidence: `tests/test_gallery_index_http.py`
- Tests: status / incremental / duplicates / similar + search-source freeze
- Rollback: delete the four routes
- Layer: B (extends D-013)

## D-016 Studio img2img / inpaint canvas

- Date: 2026-08-15
- Capability: gen.img2img_inpaint_canvas
- Existing behavior: compile existed; Studio was txt2img only.
- Chosen: `GET /api/studio/source-image` plus canvas on `/app` Studio and classic `/studio`. Same `/api/nai/generate` client. No paid call.
- Evidence: `tests/test_studio_canvas.py`
- Tests: encode, route, UI markers
- Rollback: remove source-image route and canvas UI
- Layer: B

## D-017 Kernel into chat after v1.6/v1.7 pass

- Date: 2026-08-15
- Capability: assist.tool_loop
- Existing behavior: D-014 forbade planning.py imports.
- Chosen: wire via `butler/tool_loop_bridge.py` + `butler/chat.py` / `auto_exec.py`. Keep the planning.py import lock. Cost/destructive still WorkflowRequest / confirm tickets.
- Evidence: `docs/top-tier-upgrade/GATE_REVIEW.md`, `tests/test_companion_v19.py`, `tests/tooling/test_kernel_tools.py`
- Tests: generate_image → workflow_requested; compile preview succeeds; planning import lock
- Rollback: stop calling `execute_chat_action` from chat
- Layer: B (extends D-014)

## D-018 v1.9 memory without TTS barrel

- Date: 2026-08-15
- Capability: assist.memory_confirmed / assist.proactive_events / assist.tts
- Existing behavior: one deferred row `assist.memory_tts_emotion` at 4.0.
- Chosen: implement confirmed memory, handoff, local proactive events, quiet hours. Split TTS into a non-core row. Do not cancel v1.9. Forbid screen/hooks/God Agent.
- Evidence: `butler/companion_state.py`, `tests/test_companion_v19.py`
- Tests: unconfirmed not recalled; quiet/rate; handoff desks only; tts.core=false
- Rollback: stop serving `/api/companion/*`
- Layer: B
