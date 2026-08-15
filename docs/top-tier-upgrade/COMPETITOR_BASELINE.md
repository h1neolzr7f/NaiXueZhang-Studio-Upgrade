# Competitor baseline (behavior only)

No competitor source was cloned. AGPL/GPL projects are studied as behavior, not copied. Manga-Editor-Desu-NAI remains OUT_OF_SCOPE.

| Competitor | Overlap strength | Decision | Studio response | Evidence in this repo |
|---|---|---|---|---|
| NAIWeaver | V4.5, img2img/inpaint, Precise Reference, Vibe, PNG round-trip | implement subset | Extend `nai_api.generate_image`; report uncompiled image/mask/vibe; no second client | `nai_char_modules/generation.py`, `docs/top-tier-upgrade/NAI_PARAM_MATRIX.md` |
| Infinite Image Browsing | incremental index, similar/dup, semantic search, virtual albums | implement FTS/dup first; defer semantic; exclude SD/Comfy ingest | Keep NAI-only gate; cloud bench is synthetic only | `search.py`, `nai_image_metadata.py`, `scripts/bench_gallery.py` |
| Semi-Auto-NovelAI-to-Pixiv (AGPL) | batch vibe/inpaint, upscale, mosaic, Pixiv upload | replace ANR hard path; exclude Cookie upload and plugin store | Keep Playwright + confirmation | `post_pipeline.py`, `pixiv_web_upload.py` |
| LingChat (AGPL) | Tool registry/loop, per-round auth, proactive intents | implement ideas in `butler/tooling`; exclude God Agent, hooks, screen | Do not replace LangGraph | `butler/tooling/`, `tests/tooling/` |
| Langbai NovelAI Studio | portable install, token isolation, project restore | implement install/doctor UX; exclude multi-provider and manga storyboard | Windows first | `INSTALL.bat`, `scripts/doctor_windows.ps1` |
| NyaNovel | light generate panel, fast iterate | exclude as replacement | Steal information hierarchy only | `frontend/src/pages/StudioPage.tsx`, `web/studio.js` |
| NAI-Utility-Tool (GPL) | official Vibe/Precise Ref, ONNX upscale, SuperDrop | implement behavior; exclude source copy | MIT/GPL boundary | `post_pipeline.py`, PENDING WIN-008 |
| Manga-Editor-Desu-NAI | none in this plan | exclude / OUT_OF_SCOPE / SUPERSEDED_OUT_OF_SCOPE | Do not connect, audit, or score against it | `docs/top-tier-upgrade/DECISIONS.md` D-006 |
