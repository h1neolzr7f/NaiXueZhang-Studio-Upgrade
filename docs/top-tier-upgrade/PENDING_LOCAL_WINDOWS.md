# PENDING_LOCAL_WINDOWS

Cloud cannot claim these verified. Each item must be run on Windows 10/11, preferably CPython 3.13 x64.

## WIN-001 BAT/PowerShell launchers

- Capability: start.one_click_launch
- Why cloud cannot verify: no cmd.exe/powershell.exe
- Related: tests/test_startup_safety.py, START_GALLERY.bat, INSTALL.bat
- Required Windows environment: clean dir, optional existing .venv
- Exact validation steps: `python -m pytest tests/test_startup_safety.py -q`
- Expected result: all tests pass
- Failure meaning: one-click start contract broken
- Responsible local role: W4 / local Lead
- Status: queued

## WIN-002 One-click first run

- Capability: start.one_click_launch
- Why cloud cannot verify: no desktop/browser/Windows venv bootstrap
- Related: 一键启动.bat, INSTALL.bat
- Required Windows environment: extracted zip without system Python preferred
- Exact validation steps: double-click 一键启动.bat; wait for http://127.0.0.1:8797/ and `/api/config`
- Expected result: health OK, browser opens or GALLERY_NO_BROWSER respected
- Failure meaning: first-run bootstrap failed
- Responsible local role: local Lead
- Status: queued

## WIN-003 EXE / one-click zip

- Capability: Windows 安装与上手
- Why cloud cannot verify: make_release.ps1 and portable CPython 3.13 bundling
- Related: scripts/make_release.ps1, scripts/build_windows.ps1
- Required Windows environment: git clean tree, Node 20+, Python 3.13
- Exact validation steps: `powershell -File scripts/build_windows.ps1 -Profile full -BundlePythonRuntime -SkipShortcut -SkipSampleData`
- Expected result: zip + release_manifest.json, verify_release_stage passes
- Failure meaning: cannot ship Windows package
- Responsible local role: W4
- Status: queued

## WIN-004 Console hidden / taskbar

- Capability: start.one_click_launch
- Why cloud cannot verify: wscript launch_server.vbs and Explorer taskbar
- Related: scripts/launch_server.vbs
- Required Windows environment: interactive desktop
- Exact validation steps: start via 一键启动.bat; confirm no persistent console; taskbar shows expected window
- Expected result: hidden console, app reachable
- Failure meaning: beginner UX regression
- Responsible local role: local Lead
- Status: queued

## WIN-005 Chinese / long path / NTFS

- Capability: start.one_click_launch
- Why cloud cannot verify: NTFS and cmd quoting
- Related: test_startup_safety path-with-space-and-apostrophe
- Required Windows environment: directory with space and `'`
- Exact validation steps: copy tree to `C:\\t\\installer's project` and run INSTALL.bat noninteractive
- Expected result: exit 0
- Failure meaning: install breaks on real user paths
- Responsible local role: W4
- Status: queued

## WIN-006 File watch / junction / network drive

- Capability: ingest / gallery
- Why cloud cannot verify: no NTFS junctions or offline drives
- Related: gallery_maintenance.py, crawler_watchdog.py
- Required Windows environment: local folder + junction + optional disconnected network path
- Exact validation steps: import NAI PNG via drop; create junction; disconnect mapped drive; confirm errors are explicit, no crash, no silent data loss
- Expected result: fail closed with readable error
- Failure meaning: index/file identity corruption
- Responsible local role: W2
- Status: queued

## WIN-007 Defender / signature

- Capability: Windows 安装与上手
- Why cloud cannot verify: SmartScreen/Defender
- Related: BUNDLE_NOTICE.txt, make_release.ps1
- Required Windows environment: consumer Windows with Defender on
- Exact validation steps: download/copy zip, note SmartScreen, record unsigned status in handoff
- Expected result: documented, not silently blocked without notice
- Failure meaning: users cannot start
- Responsible local role: local Lead
- Status: queued

## WIN-008 DirectML / ONNX

- Capability: post.pipeline
- Why cloud cannot verify: no Windows GPU/DirectML
- Related: post_pipeline.py
- Required Windows environment: optional NVIDIA/AMD + DirectML
- Exact validation steps: after local upscale work exists, run one local upscale and record engine name
- Expected result: engine declared; no hidden quality loss
- Failure meaning: post remains ANR-blocked
- Responsible local role: W4
- Status: queued

## WIN-009 Live2D

- Capability: assist.live2d_dock
- Why cloud cannot verify: no GPU compositor / Windows WebView
- Related: web/shared/companion-dock.js
- Required Windows environment: desktop session
- Exact validation steps: open studio, confirm one companion model loads, idle/thinking states change
- Expected result: one model, recoverable from error
- Failure meaning: companion dock broken
- Responsible local role: local Lead
- Status: queued

## WIN-010 Real large gallery

- Capability: search.fts_works_prompt
- Why cloud cannot verify: no 10k/100k user library
- Related: scripts/bench_quick.py, docs/top-tier-upgrade/BENCHMARKS.md
- Required Windows environment: SSD, recorded CPU/RAM
- Exact validation steps: build sample gallery or use local library; run bench script; record p95
- Expected result: numbers with hardware notes
- Failure meaning: performance claims unverified
- Responsible local role: W2
- Status: queued

## WIN-011 GPU and memory

- Capability: gen / post
- Why cloud cannot verify: this VM has no user GPU
- Related: generation_jobs.py, post_pipeline.py
- Required Windows environment: record GPU name and RAM
- Exact validation steps: generate 1 free-eligible mock-or-controlled job if authorized; watch memory
- Expected result: UI stays responsive; no unbounded growth
- Failure meaning: production path not local-viable
- Responsible local role: local Lead
- Status: queued

## WIN-012 Controlled real NAI

- Capability: gen.studio_frozen_txt2img
- Why cloud cannot verify: no real token authorized; paid tests forbidden here
- Related: tests/test_p0_paid_security.py
- Required Windows environment: user-provided token, explicit count limit 1, force_free if possible
- Exact validation steps: user confirms; one generate; confirm ledger unknown/spent fields; no retry on 5xx
- Expected result: one request, credentials not logged
- Failure meaning: live API contract drift
- Responsible local role: user + local Lead
- Status: blocked_needs_user

## WIN-013 Controlled Pixiv

- Capability: publish.pixiv_browser
- Why cloud cannot verify: no browser login / credentials
- Related: pixiv_web_upload.py
- Required Windows environment: local Chrome, user account, draft-only
- Exact validation steps: prepare submission; do not upload unless user confirms; cancel path
- Expected result: preview only unless confirmed
- Failure meaning: publish safety broken
- Responsible local role: user + local Lead
- Status: deferred_by_user

## WIN-014 Upgrade / uninstall / data keep

- Capability: start / recover
- Why cloud cannot verify: no v1.4 data directory on this VM
- Related: docs/UPGRADE.md
- Required Windows environment: copy of v1.4 `data/` (user-owned)
- Exact validation steps: follow docs/UPGRADE.md; start v1.5; gallery opens; uninstall/delete app dir does not delete a relocated gallery
- Expected result: schema upgrades; user files remain
- Failure meaning: data loss risk
- Responsible local role: local Lead
- Status: queued

## WIN-015 doctor / verify / DPAPI

- Capability: 数据和付费安全
- Why cloud cannot verify: DPAPI and verify.ps1
- Related: scripts/doctor_windows.ps1, scripts/run_tests_windows.ps1, tests/test_plaintext_at_rest.py
- Required Windows environment: Windows 10/11
- Exact validation steps: `powershell -File scripts/doctor_windows.ps1`; `powershell -File scripts/run_tests_windows.ps1 -SkipBrowserTests`
- Expected result: doctor read-only; verify green; tokens stored as dpapi:v1:
- Failure meaning: Windows quality gate failed
- Responsible local role: W4
- Status: queued
