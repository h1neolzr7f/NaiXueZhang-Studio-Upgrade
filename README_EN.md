<div align="center">

# 🐾 NaiXueZhang Studio

### A local-first NovelAI asset library and production workspace

**Discover references · verify metadata · manage prompts · swap characters · queue generations · post-process · prepare Pixiv releases**

[中文](README.md)

![Release](https://img.shields.io/badge/Release-v1.5.0-6f42c1)
![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Local First](https://img.shields.io/badge/Privacy-Local--first-7A5AF8)

[Download the v1.5.0 Windows package](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases/tag/v1.5.0) ·
[User guide](docs/user-guide.md) ·
[Roadmap](ROADMAP.md) ·
[Contributing](CONTRIBUTING.md)

</div>

<p align="center">
  <img src="docs/screenshots/01-gallery.png" alt="Local NovelAI gallery with search, collections, and assistant sidebar" width="900">
</p>

<p align="center">
  <img src="docs/screenshots/02-studio.png" alt="NovelAI prompt workspace and generation settings" width="440">
  &nbsp;
  <img src="docs/screenshots/03-butler.png" alt="Local workflow assistant with explicit safety boundaries" width="440">
</p>

> [!TIP]
> New users should start with the [v1.5.0 one-click Windows archive](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases/tag/v1.5.0). The frozen v1.4 interface and historical releases remain available in the [stable line](https://github.com/h1neolzr7f/NaiXueZhang-Studio).

## Why it exists

Generating one image is easy. Keeping thousands of references, prompts, characters, sources, paid tasks, derived files, and release records consistent over time is the harder engineering problem.

NaiXueZhang Studio turns that scattered workflow into one recoverable local system:

| Fragmented task | Integrated workflow |
|---|---|
| Browse folders containing thousands of images | SQLite FTS, metadata validation, facets, and source tracking |
| Copy prompts and character traits by hand | Prompt assets, character swapping, drafts, and reusable recipes |
| Lose state when a paid request or app crashes | Persistent task state, frozen parameters, and explicit unknown-charge handling |
| Run separate upscale, censor, and metadata scripts | A single post-processing and pre-publication pipeline |
| Leave provider tokens in plain configuration | Windows DPAPI, local session tokens, and fail-closed writes |

This is not another single-image generator. It is a **local-first creative asset and production platform** for repeatable NovelAI workflows.

## Main capabilities

- Strict NovelAI metadata admission and provenance records
- Searchable local galleries, tags, characters, styles, prompts, and sources
- Drag-and-drop local library ingestion
- Character replacement and persistent multi-token generation queues
- Crash recovery without silently retrying chargeable requests
- Upscaling, censorship, metadata cleanup, and publication checks
- Pixiv draft preparation and release records
- Local assistants separated into read-only help, named diagnostics, and confirmed production actions

## Quick start

Requirements: Windows 10/11. The source build uses Python 3.13.

1. Download and fully extract the [v1.5.0 archive](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases/tag/v1.5.0).
2. Double-click the included launcher.
3. Open `http://127.0.0.1:8797/` if the browser does not open automatically.
4. Add provider credentials only inside the local settings UI.

From source:

```powershell
git clone https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade.git
cd NaiXueZhang-Studio-Upgrade
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.core.lock.txt
python server.py
```

## Engineering highlights

- FastAPI local service with a React/TypeScript workspace
- SQLite FTS, schema migrations, atomic file writes, and persistent jobs
- Windows DPAPI credential protection; plaintext persistence is rejected when encryption is unavailable
- Localhost write-session tokens and path traversal protection
- Charge-aware task semantics: HTTP 5xx responses are not silently retried
- Sensitive-data scanning, packaging checks, and regression tests
- Explicit provenance, author exclusion, recoverable cleanup, and exportable source manifests

## Privacy and project status

The service listens on `127.0.0.1` by default. Local images, prompts, databases, generation history, and credentials are not included in releases. Optional online discovery reads third-party metadata only when the user requests it.

This is an unofficial project and is not affiliated with pixiv Inc., NovelAI/Anlatan, or other third-party services. Users remain responsible for provider terms, applicable law, and third-party rights. See [DISCLAIMER.md](DISCLAIMER.md), [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md), and [SECURITY.md](SECURITY.md).

## License

Code is released under the [MIT License](LICENSE). The code license does not grant rights to third-party images, prompts, characters, trademarks, or platform data.
