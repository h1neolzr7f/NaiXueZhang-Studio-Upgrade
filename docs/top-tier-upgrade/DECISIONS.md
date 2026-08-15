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
