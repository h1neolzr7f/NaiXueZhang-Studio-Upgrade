# C26 Worker Delivery — W1 NAI Core

Updated: 2026-08-15  
Role: W1 (NAI compile / transport lock)  
Requested model: Grok 4.6, xhigh, Fast  
Actual model: `cursor-grok-4.6-high-fast` (xhigh is not separately selectable)  
Repo: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` only  
Manga-Editor-Desu-NAI: not connected

## 1. Identity

| Field | Value |
|---|---|
| worker_id | W1 |
| run | https://cursor.com/agents/bc-e479afc0-6800-53a3-abbc-2a25955be753 |
| baseline_branch | `cursor/cloud-top-tier-integration-f036` @ `4d8dbea13eb166c4351c4e31f55ecc658bd40c6d` |
| worker_branch | `cursor/cloud-w1-nai-core-f036` @ `35808c6f15052a88f90fcdd821900d165178988a` |
| main | untouched (`008de38ad4dc6c8afbf0ec32ae411cd85685ac02`) |
| phase / wave | Phase 0 / Wave 2 |

## 2. Scope compliance

| Rule | Result |
|---|---|
| Only Studio-Upgrade | yes |
| No Manga connection | yes |
| No second NovelAI client | yes; `nai_api.generate_image is nai.generate.generate_image` |
| Did not edit `butler/planning.py`, `store.py`, `agents.py`, `workflow_runtime.py` | yes |
| Did not edit gallery index | yes |
| Did not edit `nai_char_modules/generation.py` | yes (Lead-owned this wave) |
| Did not implement img2img UI | yes |
| Did not change default `force_free` | yes; still `True` on compile and transport |
| Did not send real NAI requests / use real tokens | yes |
| Did not merge `main` | yes |

Allowed new files only:

- `tests/test_nai_param_snapshots.py`
- `docs/top-tier-upgrade/W1_NAI_AUDIT.md`

## 3. Read-only compile path

```
comment / Studio draft
  -> nai_char.build_generate_payload
  -> nai_char_modules.generation.build_generate_payload
  -> nai.generate.generate_image
  -> POST {IMAGE_API_BASE}/ai/generate-image
```

Facade lock: `nai_char.build_generate_payload is generation.build_generate_payload`.  
Transport lock: `nai_api.py` re-exports `nai.generate.generate_image` and does not assign a second function.  
Official image POST string `/ai/generate-image` exists only in `nai/generate.py`.  
Director stays on `/ai/augment-image` and is not the txt2img compile path.  
Xianyun is a different provider adapter over the same compile payload, not a second NovelAI client.

HTTP body constructed in `nai/generate.py` (no network in this audit):

```
input / model / action / parameters / use_new_shared_trial=false
```

Compile-only metadata is **not** copied into that body:

- `requested_action`
- `unsupported_fields`
- `unknown_fields`
- `free_eligible` / `resized_for_free` (result fields, not POST keys)

D-009 holds: production HTTP `action` remains `generate`.

## 4. Matrix vs current compile

Matches `docs/top-tier-upgrade/NAI_PARAM_MATRIX.md` on this SHA:

| Field / mode | Compiled into HTTP? | Current lock |
|---|---|---|
| V4.5 Full / Curated / V4 Full | yes | Source maps; explicit `nai-diffusion-*` wins; silent default is `nai-diffusion-4-5-full` |
| width/height/steps | yes | `force_free=True` fits long-edge 1216 and 1024² pixels, caps steps at 28 |
| sampler / scale / cfg_rescale / noise_schedule | yes | pass-through with documented defaults |
| qualityToggle / UC | yes | `uc` and `negative_prompt` mirrored; `negative_prompt` wins if both set |
| seed | yes if int and `>= -1` | `-1` and `0` kept; `-2` / non-int / blank omitted |
| characterPrompts / v4 char slots | yes | negative captions padded to slot count |
| Precise Reference | yes as reference arrays | still `action=generate`; `free_eligible=false` |
| Vibe Transfer | no | all four vibe keys listed in `unsupported_fields` |
| img2img / inpaint / infill | no | `requested_action` recorded; HTTP stays `generate`; `image`/`mask` omitted from parameters |
| Enhance / Director | separate path | `/ai/augment-image` |
| Anlas estimate | not in compile | payload has no `anlas` / `anlas_spent` |
| unknown vendor keys | no | sorted into `unknown_fields` |

`inpaintImg2ImgStrength` **is** compiled into parameters even when `image`/`mask` are not. Locked as current behavior; not an img2img implementation.

## 5. Boundaries (locked by snapshot tests)

`fit_opus_free_size`:

| input | output |
|---|---|
| `0,0` or negative | `832,1216` + resized |
| `832x1216` / `1216x832` / `1024x1024` | unchanged |
| `1216x1216` | `1024x1024` (scale is exactly `1024/1216`) |
| `2048x2048` | `1024x1024` |

Other boundaries:

- Default `force_free=True` when the caller omits the kwarg; `2048²` / 50 steps becomes `1024²` / 28.
- `force_free=False` keeps `1472²` / 36 steps (below `2 * 1216`).
- `force_free=False` still fits `2500²` because `2500 > 2432`; steps stay 36; `free_eligible` stays false.
- `width=0` / `height=0` use the `or 832` / `or 1216` defaults, so the free-fit path sees a legal Opus size and `resized_for_free` stays false.
- `requested_action` wins over `action`.
- `INFILL` lowercases to `infill` and is reported as `action:infill`.

## 6. Findings for Lead (do not patch in this Worker)

1. **Stale characterization test.** `tests/test_nai_char_module_contracts.py` still asserts the compile result key set **without** `requested_action` / `unsupported_fields` / `unknown_fields`. D-009 already added those keys. W1 did not edit that file. Lead should extend the expected set; do not revert generation.py.
2. **Unknown action strings are silent.** `action=upscale` (or any value outside `{generate,img2img,inpaint,infill}`) becomes `requested_action=generate` and is listed in neither `unsupported_fields` nor `unknown_fields` because `action` is a known key. Current behavior is snapshotted, not changed.
3. **Negative size without `force_free` is not clamped.** `width=-10, height=1216, force_free=False` stays `-10`. Only the free-fit path rejects `<= 0`.
4. **`_aitag_source` is an unknown compile field.** Routes attach it before generate. If the same dict is compiled, it appears in `unknown_fields` and is not sent. Harmless; do not special-case it in generation.py without a Lead decision.
5. **`gen.img2img_inpaint_canvas` remains 3.0.** Reporting is not a canvas or a compiled img2img/inpaint HTTP action. Do not raise the barrel on this Worker.

## 7. Capability deltas

| capability_id | before | after | decision |
|---|---:|---:|---|
| gen.studio_frozen_txt2img | 7.0 | 7.0 | snapshots lock txt2img + `force_free`; no paid proof |
| gen.img2img_inpaint_canvas | 3.0 | 3.0 | reported, not compiled; no UI |
| restore.png_stealth_v4 | 7.0 | 7.0 | vibe/mask still dropped from HTTP |
| gen.cancel_balance_error | 8.0 | 8.0 | transport unread beyond body isolation |

Barrel lowest stays **3.0**. W1 does not claim v1.6 complete.

## 8. Tests

Commands (cloud-safe, no token):

```powershell
python -m pytest -q tests/test_nai_param_snapshots.py tests/test_nai_generate_compile.py
python -m compileall -q -x "runtime|\.venv|node_modules|data" nai nai_api.py nai_char_modules tests/test_nai_param_snapshots.py
```

Recorded on this Worker: `34 passed, 13 subtests passed` for `tests/test_nai_param_snapshots.py` + `tests/test_nai_generate_compile.py`.  
Known pre-existing fail if the characterization file is included: `test_generate_payload_characterization_preserves_cost_and_v4_contract` (finding 1).

No official HTTP POST is executed by these tests. Body isolation is AST + local dict mirror of `nai/generate.py`.

## 9. Explicit non-goals

- img2img / inpaint canvas or HTTP `action` change
- second NovelAI client
- default `force_free` flip
- Anlas estimator
- Director / Enhance compile merge
- wiring into `planning.py` / Tool Loop
- real token calls

## 10. Blockers

- CRED-001: real NAI/Pixiv tokens and paid verification are not authorized.
- Lead must update the stale characterization key set before claiming the D-009 compile contract green on the full suite.

## 11. Rollback

```powershell
git checkout cursor/cloud-top-tier-integration-f036
```

Or delete `cursor/cloud-w1-nai-core-f036`. No `main` merge, no force-push.

## 12. Next (Lead)

1. Cherry-pick or merge only the two W1 files onto `cursor/cloud-top-tier-integration-f036` after reviewing the stale contract test.
2. Keep HTTP `action=generate` until a dedicated img2img compile is accepted with UI + tests.
3. Do not start v1.6 inpaint UI from this audit.
