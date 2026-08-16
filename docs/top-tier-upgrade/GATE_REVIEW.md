# Formal gate review: v1.6 / v1.7

Date: 2026-08-15  
Mode: `CLOUD_WEB`  
Branch: `cursor/cloud-top-tier-integration-f036`  
Repository: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` only  
This is a cloud checkpoint review, not a claim that the whole upgrade is done.

## Verdict

| Gate | Result | Notes |
|---|---|---|
| v1.6 NAI compile + Studio canvas | **PASS (cloud)** | Single client compiles `img2img` / `infill`. Studio `/app` and classic `/studio` can load a local source image, set `action`, paint an inpaint mask, and put `image`/`mask`/`strength` on the frozen comment. No second NovelAI client. No paid call. |
| v1.7 gallery index HTTP | **PASS (cloud)** | Dirty-set incremental, exact/near dups, local similar. Additive HTTP only. `/api/ai_works_search` JSON unchanged. No second store. Embed stays `local_none`. Not a 10k/100k Windows bench. |
| v1.8 kernel → chat | **PASS after the two gates above** | Kernel is wired through `butler/tool_loop_bridge.py` and `butler/chat.py`. `planning.py` still does not import `butler.tooling`. Paid/destructive tools still only produce `WorkflowRequest` / existing confirm tickets. |
| v1.9 | **implemented, not cancelled** | Confirmed memory, persona handoff, proactive local events, quiet hours / rate limit. TTS is **not** a core barrel item. Screen / key-mouse hooks / God Agent remain forbidden. |
| Windows WIN-001..015 | **not this review** | Still local takeover. |
| Merge `main` / Release / real NAI token | **forbidden** | Unchanged. |

## v1.6 evidence

- Compile lock: `tests/test_nai_generate_compile.py`, `tests/test_nai_param_snapshots.py`
- Source image: `GET /api/studio/source-image` → raw PNG base64 for compile, not a second HTTP client
- UI: `frontend/src/pages/StudioPage.tsx`, `web/studio.html`, `web/studio.js`
- Tests: `tests/test_studio_canvas.py`, `tests/test_studio_workbench.py`
- Paid gate: default `force_free=true`; image/mask input makes `free_eligible=false`

Fail conditions that did **not** happen: second NovelAI client; vibe compiled as HTTP image; lone `image` without explicit img2img/inpaint becoming `img2img`.

## v1.7 evidence

- Library: `gallery_index.run_incremental` (moved out of `db.py` so the quality gate line budget stays honest)
- HTTP:
  - `GET /api/gallery/{gallery_id}/index/status`
  - `POST /api/gallery/{gallery_id}/index/incremental`
  - `GET /api/gallery/{gallery_id}/duplicates`
  - `GET /api/gallery/{gallery_id}/similar`
- Tests: `tests/test_gallery_index.py`, `tests/test_gallery_index_http.py`
- Search freeze: `api_search` still returns the same payload keys via `serialize_gallery_payload`

Albums / move journal remain design-only. Do not treat `scripts/bench_gallery.py` as 10k.

## Quality gate honesty

PR #3 CI on tip `ad83173` failed for two reasons. Neither was fixed by deleting tests or lowering `p1 == 0`:

1. Windows `TemporaryDirectory` could not delete `gallery.db` while SQLite was still open. Test now closes the `Database` inside the `with` block.
2. `db.py` exceeded 1000 lines after `incremental_index` was added. The method moved to `gallery_index.run_incremental`.
3. POSIX Regression Guard called `python` which is absent on this VM. Guard now tries `python3` then `python`. The assertion in `tests/test_product_quality_gate.py` is unchanged.

## Kernel wiring allowed only because both gates passed

- New: `butler/tool_loop_bridge.py`
- Chat: `compile_nai_preview` / `gallery_index_preview` go through `ToolExecutor`
- `butler/planning.py` import lock remains (`tests/tooling/test_kernel_tools.py`)
- `generate_image` and other cost/destructive names still cannot execute inside the interactive loop

## Explicit non-claims

- Not Windows-verified
- Not paid-generation verified
- Not Pixiv-account verified (`WIN-013` still deferred)
- Not a Release
- Not a `main` merge
