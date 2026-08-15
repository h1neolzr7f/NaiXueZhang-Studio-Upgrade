# Competitor baseline (behavior only)

No competitor source was cloned. AGPL/GPL projects are studied as behavior, not copied.

| Competitor | Overlap strength | Decision | Studio response |
|---|---|---|---|
| NAIWeaver | V4.5, img2img/inpaint, Precise Reference, Vibe, PNG round-trip | implement subset | Extend existing `nai_api.generate_image`; no second client |
| Infinite Image Browsing | incremental index, similar/dup, semantic search, virtual albums | implement FTS/dup first; defer semantic; exclude SD/Comfy ingest | Keep NAI-only gate |
| Semi-Auto-NovelAI-to-Pixiv (AGPL) | batch vibe/inpaint, upscale, mosaic, Pixiv upload | replace ANR hard path; exclude Cookie upload and plugin store | Keep Playwright + confirmation |
| LingChat (AGPL) | Tool registry/loop, per-round auth, proactive intents | implement ideas in butler/tooling; exclude God Agent, hooks, screen | Do not replace LangGraph |
| Langbai NovelAI Studio | portable install, token isolation, project restore | implement install/doctor UX; exclude multi-provider and manga storyboard | Windows first |
| NyaNovel | light generate panel, fast iterate | exclude as replacement | Steal information hierarchy only |
| NAI-Utility-Tool (GPL) | official Vibe/Precise Ref, ONNX upscale, SuperDrop | implement behavior; exclude source copy | MIT/GPL boundary |
| Manga-Editor-Desu-NAI | none in this plan | exclude / OUT_OF_SCOPE | Do not connect, audit, or score against it |
