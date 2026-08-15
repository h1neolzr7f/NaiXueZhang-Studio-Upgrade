# NAI parameter compatibility matrix

Base: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` @ `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`  
Compile path: `nai_char_modules/generation.py` → `nai_char.build_generate_payload` → `nai_api.generate_image` (`nai/generate.py`).  
No second NovelAI client.

| Field / mode | Comment / UI source | Compiled into HTTP? | Current behavior | Decision |
|---|---|---|---|---|
| V4.5 Full | `Source` contains V4.5, or default | yes, `model=nai-diffusion-4-5-full` | default product model | implement |
| V4.5 Curated | explicit `model` | yes | explicit model wins | implement |
| V4 Full | `Source` contains V4 | yes | mapped | implement |
| width/height | comment | yes | 64-multiple free fit when `force_free` | implement |
| sampler / steps / scale | comment | yes | default k_euler_ancestral / 28 / 5 | implement |
| cfg_rescale / noise_schedule | comment | yes | passed through | implement |
| qualityToggle / UC | comment | yes | `uc` and `negative_prompt` mirrored | implement |
| seed | comment | yes if int and `>= -1` | `-1` kept; invalid omitted | implement |
| characterPrompts / v4 char slots | comment | yes | negative captions padded | implement |
| Precise Reference | `reference_image_multiple*` | yes as reference arrays | still `action=generate` | implement |
| Vibe Transfer | `xianyun_vibe` / `vibe*` | no official compile | reported in `unsupported_fields` | implement |
| img2img / inpaint | `image` / `mask` / `action` | no | `requested_action` recorded; HTTP stays generate | implement |
| Enhance / Director | `nai/director.py` | separate path | not txt2img compile | defer |
| Anlas estimate | ledger / work order | not in compile | `unknown` until provider returns | implement |
| unknown vendor keys | any other comment key | no | listed in `unknown_fields` | implement |

Production HTTP `action` remains `generate` until a dedicated img2img/inpaint compile is accepted after tests lock the current payload.
