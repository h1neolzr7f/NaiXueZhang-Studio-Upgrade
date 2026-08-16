# Autonomous final report — Cloud RC

Date: 2026-08-16  
Branch: `cursor/autonomous-next-architecture-96fe`  
Base: `cursor/cloud-top-tier-integration-f036` @ `0e6564b`  
Draft PR: https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/12  
**Do not merge `main`. Do not ship a Release. Do not run real paid NovelAI or Pixiv login in cloud.**

## Verdict

**Cloud RC: YES** for Linux-executable correctness, safety locks, and synthetic product loops.

This is not a Windows release and not a top-tier performance claim. The user should verify Windows / DPAPI / real accounts / real paid Anlas / subjective UX. Ordinary code holes that Linux/stub/synthetic can see were hunted and fixed here.

## What landed

| Plan item | Status |
|---|---|
| P1-A paid NAI one-time ticket | Done. Before token pick and HTTP. Replay/expiry/hash mismatch → 403. |
| P1-B `materialize_asset` | Done for QQ/drop/Codex/synthetic. Pixiv intake still allow-listed. |
| P2-A keyset continuation | Done. 501/1001 tests. |
| P2-B unindexed/stale anti-join | Done. Scoped reconcile. |
| P2-C t+1 bands dHash+pHash | Done. Cross-bucket Hamming 1/2. |
| P2-D source-qualified RemoteAssetRef | Done. `WorkRef` unchanged. |
| D-019 facts + Online/Library | Done on classic `/`「在线发现」. Favorite = reference. Add to library materializes. |
| Lineage | Minimal fields + `recipe_fingerprint`. |
| Capability plane | Registry / Gateway / Delegation / Typed Handoff / Orchestrator deny-all execute. |
| Self-test loop | Two full greens + mutation BREAK 7/7 RED. |

## Bugs cloud found (do not regress)

See `AUTONOMOUS_TEST_EVIDENCE.md` wave 1. Highest product impact:

- Paid subset retry would 403 after a partial failure.
- Char-swap paid run had no ticket issuer in the UI.
- `_paid_authorized` from the caller was a bypass; now only a persisted frozen job can reuse authorization.
- Classic `/` never showed the React Online gallery; Online is now a gallery-source button, not a ninth nav item.

## Loops completed

1. Implement → first BREAK (14 real issues) → fix → targeted green  
2. Mutation BREAK (7 detectors all RED) → restore → full suite ×2 + quality gate ×2  

No third architecture rewrite. No God Agent. No second NAI client or job manager.

## Regression Preservation Matrix

| Capability | Status | Evidence |
|---|---|---|
| 批量换角 | EXTENDED (ticket + authorize UI) | `test_char_swap_*`, `test_nai_authorization`, generation job tests |
| Studio | EXTENDED (authorize then generate) | `test_studio_canvas`, `test_nai_authorization` |
| txt2img / img2img / inpaint compile | UNCHANGED compile path | existing NAI compile/snapshot tests |
| GenerationJobManager | UNCHANGED lifecycle | `test_generation_jobs.py` |
| billing_unknown / billing_uncertain | UNCHANGED no auto-retry | `test_generation_jobs.py` |
| Butler receipt / confirm | ADAPTED (issues same ticket) | butler execute/batch_ops |
| Pixiv intake | UNCHANGED (still own SQL) | existing pixiv tests; allow-listed |
| QQ ingest / local drop | ADAPTED (writer) | `test_library_writer_and_remote.py` |
| AITag online | UNCHANGED | existing aitag tests |
| FTS / duplicates / similarity | EXTENDED (bands + keyset) | index continuation + existing index tests |
| snapshots | UNCHANGED | `test_gallery_snapshot.py` |
| generated gallery | UNCHANGED | existing generated tests |
| post pipeline | UNCHANGED | existing pipeline tests |
| classic Gallery UI | EXTENDED (在线发现) | `test_online_library_e2e.py` UI lock + site nav 8 |
| current `/app` | UNCHANGED redirect to classic | `test_workspace_stack.py` |
| WorkRef / old search JSON | UNCHANGED | existing search tests |
| security gates | UNCHANGED + new ticket | quality gate, sensitive scan, p0 paid tests |

No unverified `AT-RISK` row.

## Not done / UNKNOWN (not “no time”)

| Item | Why it stays open |
|---|---|
| Windows 一键启动 / EXE / 中文路径 | No cmd.exe / Explorer |
| DPAPI token at rest | Linux cannot mint `dpapi:v1:` |
| Real 10k/100k user library p95 | Only Linux synthetic metadata |
| Real NAI free/paid | No user token; paid forbidden here |
| Real Pixiv | User deferred; no credentials |
| Pixiv intake → writer | Planned later wrap; receipts stay |
| Site crawler SQL in `db.py` | Existing allow-list; not this freeze |
| React `GalleryPage` as `/` | Classic atlas is the product shell; React page is unused on `/` |
| Process-local ticket secret | Restart invalidates unused tickets (10 min TTL). Single-process app. |
| Multi-provider ranking | Explicitly out of scope |

P2 leftovers above all require Windows or a later adapter move. None are “skipped to go green”.

## Rollback

```bash
git fetch origin
git checkout cursor/cloud-top-tier-integration-f036
# or reset this branch to 0e6564b
```

No `main` merge. No schema flag that requires a one-way prod migration beyond existing v2. New tables are `CREATE IF NOT EXISTS` on the gallery index. Online favorites are in-memory for the synthetic provider (restart clears cloud favorites; Windows users should treat Online favorites as session-scoped until a later persist).

**Note:** synthetic Online favorites are process memory. That is acceptable for the stub provider. Real provider favorites persistence is a later additive step, not claimed here.

## Known risks

- Issuing a ticket is not by itself a human confirm; UI must confirm when `requires_ticket`. Server still rejects transport without a valid ticket.
- Retry reuse trusts the persisted job file. If that file is rewritten on disk, hashes/fingerprints must still match the remaining targets.
- 100k bench is a keyset `SELECT`, not visual hash of 100k PNGs.

## User job after checkout

Install/run on Windows, follow `AUTONOMOUS_PENDING_WINDOWS.md` shortest path, send concrete failures. Do not re-hunt ticket replay or 501 skip unless those tests were deleted.
