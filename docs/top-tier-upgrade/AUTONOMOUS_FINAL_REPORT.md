# Autonomous final report — review-closure loop

Date: 2026-08-16  
Branch: `cursor/autonomous-next-architecture-96fe`  
Peer-review HEAD that was rejected: `7e963da`  
This loop HEAD: see `git rev-parse HEAD`  
Draft PR: https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/12  
**Do not merge `main`. Do not ship a Release. Do not run real paid NovelAI or Pixiv login in cloud.**

## Verdict

Previous Cloud RC claim at `7e963da` was correctly rejected. That revision had green gates but missed SMEA cost fields, pre-confirm ticket issue, retry seal, cursor pre-insert backfill, orphan files, and source-qualified remote identity.

**Linux review-closure: YES** for the peer-review P0/P1 set after a second attack loop. This is still not a Windows release and not a paid-NAI Transform claim.

Capability Gateway remains a **decision prototype** (`EXECUTION_WIRED=False`). Free-safe Transform→Library is a local derive with lineage, not a NovelAI HTTP generate.

## What this loop closed

| Review item | Fix |
|---|---|
| [P0] SMEA bypasses paid ticket | `sm` / `sm_dyn` / `autoSmea` / `smea` force `free_eligible=False` and bind ticket hashes |
| [P1] Ticket issued before confirm | HTTP `/authorize` returns `ticket=""` until `confirmed=true`; UI is preview → confirm → issue |
| [P1] Retry can raise cost | Frozen job stores HMAC `authorization_seal`; mutating targets+fingerprints fails seal |
| [P1] Pre-cursor insert stays unindexed | Scan end runs bounded anti-join backfill |
| [P1] File ok / DB fail leaves orphan | New files are deleted when unreferenced after writer failure |
| [P1] Remote identity not source-qualified | Require `source_url` or `source_key`; digest is part of `qualified_id` |
| [声称] Transform / favorites / Capability | Local derive E2E + disk favorites + `EXECUTION_WIRED=False` |
| [P2] Guard / pair / quality gate | Tree SQL write guard, near-dup pair groups, `online-discover.js` in gate |

## Gate results after the fix

| Check | Pass 1 | Pass 2 |
|---|---|---|
| pytest `--ignore=tests/test_pixiv_selector_probe.py` | 1211 passed, 68 skipped, 127 subtests | 1211 passed, 68 skipped, 127 subtests |
| quality gate | p0=p1=p2=0 | p0=p1=p2=0 |
| `scan_sensitive.py --git-candidates --content-only` | clean | clean |
| compileall | exit 0 | — |

## Mutation BREAK (this loop)

| Mutation | Result |
|---|---|
| Remove `generate_image` paid gate | RED |
| Skip ticket consume (`_CONSUMED` write) | RED |
| `hash_bands` count=1 | RED |
| Ignore keyset `after` | RED |
| Allow delegation replay | RED |
| Drop SMEA from `free_eligible` | RED |
| Issue HTTP ticket before `confirmed` | RED |
| Skip retry authorization seal | RED |
| Skip unindexed backfill | RED |
| Restore all | GREEN, `git diff` empty |

## Cloud RC checklist (honest)

| Condition | Now |
|---|---|
| pytest ×2 / quality ×2 / content-only scan | True |
| P1/P2 deterministic counterexamples for the review set | True |
| Online → Materialize → **free-safe local derive** → Library + lineage | True |
| Paid NAI Transform → Library | False (not claimed; no real NAI) |
| 501/1001, cross-bucket pairs, delegation | True |
| unindexed final backfill | True |
| paid ticket includes SMEA cost fields | True |
| current schema v2 snapshot rollback rehearsal | True |
| real old-gallery upgrade | Windows only |
| Capability execution wired | False (prototype) |
| Matrix unverified AT-RISK | False |
| Known P0/P1 from the review | Closed |

## Windows Final QA (2026-08-16)

`LOCAL WINDOWS RC: PASS`. Details: `WINDOWS_RC_REPORT.md`.

Closed on this machine: tzdata CI, one-click per-port log, doctor GBK filename, online empty-query fallback, write-guard runtime skip, old-gallery copy index, Studio/char-swap ticket preview.

Still not claimed: public Release zip, real paid NAI, Pixiv login, Capability execution, 10k disk bench.

## Rollback

```bash
git fetch origin
git checkout cursor/cloud-top-tier-integration-f036
```

No `main` merge. Online favorites now persist under `data/online_favorites.json` (gitignored via data dir). Index tables remain `CREATE IF NOT EXISTS`.

## User job after checkout

Install/run on Windows, follow `AUTONOMOUS_PENDING_WINDOWS.md`. Cloud already locked SMEA no-ticket, unconfirmed ticket issue, retry seal, cursor pre-insert, orphan cleanup, and source-qualified remote IDs. Do not re-hunt those on Linux synthetic.
