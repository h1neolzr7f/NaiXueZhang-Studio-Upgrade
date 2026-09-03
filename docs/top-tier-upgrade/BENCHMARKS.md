# Benchmarks

Cloud Phase 0 cannot produce 10k/100k numbers. Record environment whenever a number is claimed.

## Cloud agent environment (2026-08-15)

- OS: Linux 6.12 (Cloud Agent VM)
- CPU/RAM/GPU: not a Windows production machine; do not use for barrel performance claims
- Python: 3.12.3
- Node: v22.14.0
- Image count: no user gallery
- Cache: n/a
- NovelAI network: not used
- Script: `python -m pytest -q --ignore=tests/test_pixiv_selector_probe.py`

## Cloud-safe functional timings

| Check | Result | Notes |
|---|---|---|
| Critical paid/butler/generation/gallery subset | 119 passed, 3 skipped in 2.64s | no Windows shell |
| `tests/tooling` + NAI compile lock | recorded after this change | no paid API |
| `scripts/bench_quick.py` | not run | needs local `data/aitag.db` |

## Required later (same Windows machine, same dataset)

- Cold start
- Import 1k / 10k
- Incremental 100
- Keyword / metadata / similar / semantic latency
- Thumbnail scroll + RSS
- 10/100/300 job completion
- Disconnect / cancel / crash
- Duplicate side-effect check
- 60-image queue to post
- First install to first generate
- PNG import/edit/export/reimport

Do not delete a failing benchmark. Adjust targets only with hardware evidence.
