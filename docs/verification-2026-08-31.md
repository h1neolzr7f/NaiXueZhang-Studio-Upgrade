# Local verification — 2026-08-31

Source snapshot: `5e138162637bff2cfcd6965492bb906889bbbff8`.

## Scope and environment

Windows, Python 3.13, existing local core/test dependencies. This was not a clean installation of every pinned dependency. No private library, browser profile or credentials were copied into the demo.

The service ran from an isolated copy of the public source. A local `config.json` was copied from `config.release.json` with `aitag_online_enabled` set to `false`. This runtime file, logs and generated data are excluded from publication.

## Screenshot

`screenshots/demo-studio.png` is an unedited browser capture of the running `/studio` page. It is not an AI-generated interface or a release installer screenshot.

To reproduce with a clean development copy:

1. Install core dependencies as described in the README.
2. Copy `config.release.json` to `config.json` only if the latter does not already exist. Set `aitag_online_enabled` to `false` for this demo. Do not overwrite an existing user's configuration.
3. In PowerShell, set `$env:GALLERY_PORT = "18797"`, then run `.\.venv\Scripts\python.exe server.py`.
4. Open `http://127.0.0.1:18797/studio` and enter `landscape, mountain lake, morning light, watercolor` in the main prompt.
5. Enter `A quiet mountain lake at sunrise. Documentation demo; no generation request.` in the Base field. Do not press Generate or Ctrl+Enter.
6. Capture the page without browser chrome or private paths. The screenshot shows no token, no source image and no generated result.

No generation, collection or publishing action was invoked. The screenshot demonstrates the interface and draft fields, not end-to-end external service behavior.

## Selected existing tests

```powershell
py -3.13 -m pytest -q tests/test_backend_persistence_contracts.py tests/test_qq_nai_metadata.py tests/test_batch_preview_dedup.py
```

Result: **31 passed in 7.90s**, exit code 0. The selection covers backend persistence contracts, metadata handling and batch-preview deduplication. It is not the full test suite or a throughput benchmark.

Not tested in this pass: a fresh installation with all pinned dependencies, Windows release installation, paid API requests, Pixiv collection/publishing, Android, full frontend build, or all optional integrations. See the workflow and contributing guide for broader checks.

## Maintenance regressions addressed

The existing main-branch [CI run](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/actions/runs/32863213387) reported three failures. They were reproduced locally before these changes:

- Updated a stale canary assertion to expect `force_free=True`, matching the enforced configuration. This preserves the free-tier restriction; the account-safety tests still cover subscription routing. No billing guard was relaxed.
- Added the missing `pixivResetSearch` checkbox and `pixivTaskPresets` container to the core collection page. The shared script already references these controls.
- Clarified the Android source description in `使用说明.txt`: the source starts a local service on the phone, while the Windows package contains no APK. This is source inspection, not a device test.

After the changes, with `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`:

```powershell
py -3.13 -m pytest -q --tb=short tests/test_butler_canary_contract.py tests/test_mobile_standalone.py tests/test_release_core_profile.py tests/test_nai_account_safety.py
```

Result: **25 passed, 1 warning in 2.88s**. The warning is a local Starlette/httpx dependency notice. These 25 tests are a separate selection from the 31 tests above. No external generation request was made.

## 中文说明

本次从公开源码的隔离副本启动服务，没有接入私人图库或账号。截图是实际页面，未调用生成接口。31 项既有测试通过仅代表列出的验证范围；不表示全量测试、真实付费生成或安装包均已验收。
