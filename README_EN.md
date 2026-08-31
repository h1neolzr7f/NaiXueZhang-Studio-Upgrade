# NaiXueZhang Studio

A Windows application for managing a local NovelAI image library, prompts and generation jobs. Search references, edit parameters, queue work and organize results from one interface, with images and job records stored locally.

[中文](README.md) · [Windows download](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases/tag/v1.5.2) · [User guide](docs/user-guide.md) · [Version changes](docs/UPGRADE.md)

This repository is the **v1.5.2 maintenance line**. The older v1.4 line is preserved in [NaiXueZhang-Studio](https://github.com/h1neolzr7f/NaiXueZhang-Studio). The Windows release does not include an Android APK.

## Preview

![Running Studio interface with prompt, scene and preview panels](docs/screenshots/demo-studio.png)

Captured from the actual application using an empty local library and no account credentials. The prompt is hand-written demo text. No generation request or paid API call was made; the preview is intentionally empty. See the [verification record](docs/verification-2026-08-31.md) for the environment, steps and limitations.

## What it does

- Imports local images, reads NovelAI metadata and searches works, authors, tags and prompts.
- Edits scene and character parameters, manages drafts, previews character replacement and queues generation jobs with parameter snapshots.
- Organizes results by source work, with post-processing, a recycle bin and publishing preparation tools.
- Connects to optional external services for generation, discovery, assistants and publishing. These integrations need their own configuration; opening the local interface does not require an account.

This is an unofficial project, with no affiliation to NovelAI, Pixiv or other third-party services. Their availability, account requirements and charges are controlled by those services. Use only material you have permission to process.

## Run on Windows

Download the complete package from the [v1.5.2 release](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases/tag/v1.5.2), verify the SHA-256 listed there, extract it to a writable folder and run `一键启动.bat`. Open `http://127.0.0.1:8797/`. Runtime data is stored in `data/` beside the application.

For source development, use Windows and Python 3.13:

```powershell
git clone https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade.git
cd NaiXueZhang-Studio-Upgrade
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.core.lock.txt
.\.venv\Scripts\python.exe server.py
```

The default interface is `/`; an alternative workspace is available at `/app`. Static assets are included. After changing `frontend/`, rebuild with Node.js 20+:

```powershell
npm --prefix frontend ci
npm run workspace:build
python scripts/asset_versions.py
```

Core dependencies run the local service. Assistants, browser publishing and some post-processing tools require additional setup described in the [user guide](docs/user-guide.md).

## Code map

| Location | Responsibility |
| --- | --- |
| `routes/`, `server.py` | FastAPI routes and local service entry point |
| `db.py`, `gallery_catalog.py` | SQLite, full-text search and library indexing |
| `generation_jobs.py`, `production_queue.py` | Job state, parameters and queue persistence |
| `nai/`, `butler/` | Generation and assistant implementations, behind compatibility entry points |
| `web/`, `frontend/` | Classic pages and React / TypeScript workspace |
| `tests/`, `scripts/` | Regression tests, packaging and publication checks |

One design concern is how to represent failure after an external request has already been sent. A missing response does not prove that a generation was not charged. Unknown outcomes remain explicit instead of being treated as successful or automatically resubmitted.

## Operational limits

- Studio and character replacement default to the application's free-tier parameter limits. This is not a promise of free access or a guarantee against charges.
- Submitted prompts are frozen. Requests with received HTTP 5xx responses or unknown billing outcomes are not automatically resubmitted; other failures follow their specific job-state rules.
- Batch replacement uses preview before execution. Unsent work and sent work with unknown outcomes must be handled separately after a restart.
- The service binds to `127.0.0.1` by default, uses a local session token for writes and Windows DPAPI for stored credentials. This is not a complete multi-user authentication system; do not expose it directly to the public internet.
- Local storage does not make every feature offline. Generation, assistants, discovery and publishing can send required data to configured services. Review prompts, assets and account settings before use.

## Development checks

After installing core dependencies, run a small set of existing tests without real accounts:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q tests/test_backend_persistence_contracts.py tests/test_qq_nai_metadata.py tests/test_batch_preview_dedup.py
```

On 2026-08-31, these tests reported **31 passed** locally. This is not a full-suite, paid-generation or installer validation claim. Details are in the [verification record](docs/verification-2026-08-31.md); broader checks are defined in [CI](.github/workflows/tests.yml) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing and license

For a bug, include the version, operating system, minimal reproduction steps and redacted logs. Fixes, regression cases, documentation and usability improvements are welcome. Describe the scope before starting a large change; planned work is listed in [ROADMAP.md](ROADMAP.md).

Do not upload credentials, private databases or unauthorized images in issues, pull requests or screenshots. Follow [SECURITY.md](SECURITY.md) for security reports.

Code is licensed under [MIT](LICENSE). This does not grant rights to third-party images, characters, trademarks or platform data. See [responsible use](RESPONSIBLE_USE.md) and the [disclaimer](DISCLAIMER.md).
