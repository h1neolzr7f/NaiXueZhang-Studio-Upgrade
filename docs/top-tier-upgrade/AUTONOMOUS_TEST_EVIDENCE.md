# Autonomous test evidence

Updated: 2026-08-16  
Branch: `cursor/autonomous-next-architecture-96fe`  
Commit at evidence write: see `git rev-parse HEAD`  
Cloud: Linux only. Not a Windows 10k/100k claim.

## Gate results

| Check | Pass 1 | Pass 2 |
|---|---|---|
| `pytest -q --ignore=tests/test_pixiv_selector_probe.py` | 1202 passed, 68 skipped, 127 subtests | 1202 passed, 68 skipped, 127 subtests |
| `scripts/product_quality_gate.py --json` | p0=p1=p2=0 | p0=p1=p2=0 |
| `scripts/scan_sensitive.py --git-candidates --content-only` | clean | clean |
| `python3 -m compileall -q -x "runtime\|\.venv|node_modules|data" .` | exit 0 | exit 0 |
| `npm --prefix frontend run build` + `scripts/asset_versions.py` | done | stamps refreshed after char-swap extract |

Ignored: `tests/test_pixiv_selector_probe.py` (Windows/browser). No tests deleted. `db.py` still ≤1000 lines.

## Red → Green → Break → Green

### Wave 1 — implementer + first BREAK

Real defects found after the first implementation, then locked:

1. Token check ran before ticket → missing-token hid authorization failures. Fixed: authorize → token → enqueue.
2. Butler ticket action had to be `studio_generate` to match `start_studio_generate`.
3. Ticket targets must use `build_studio_targets` (seed / `_studio_snapshot`) or manifest hash mismatches.
4. `preview_only` still launched a job; tests patch `_launch_job`.
5. Drop tests patch `get_db` / `now_iso` / `ensure_gallery_dirs` → writer accepts injected `db` and `acquired_at`.
6. Reimport must keep `create_date` via `now_iso()` patch.
7. `visibility_counts` on a hash-only memory DB must swallow missing `work_images`.
8. Online favorite during provider `unavailable` must show `available=False`.
9. GalleryPage `items` used before `useMemo` (workspace page still not the classic `/` shell).
10. Gateway must consume the injected `DelegationStore`, not only the module singleton.
11. **Paid subset retry compared subset compile hashes to the full-job hashes → legitimate retry 403.** Fixed: look up the frozen job; reuse only when current fingerprints ⊆ stored fingerprints. Caller `_paid_authorized` is ignored.
12. **Char-swap UI called `/batch/run` without a ticket → every img2img batch 403.** Fixed: `/batch/authorize` + Remix/classic confirm; HTTP 403 on ticket errors.
13. **`batch.js` grew past the 925-line orchestrator budget.** Fixed: `authorizeAndRunBatch` lives in `api.js`.
14. **React `GalleryPage` is not the `/` product.** Classic `index.html` now has「在线发现」without a ninth primary nav item.

### Wave 2 — mutation BREAK (all RED, then restored)

| Mutation | Expected red test | Result |
|---|---|---|
| Remove `generate_image` paid gate | `test_generate_image_blocks_transport_without_authorization` | RED |
| Skip `start_batch` authorize | `test_missing_ticket_is_rejected_before_enqueue` | RED |
| `hash_bands` count = 1 | `test_cross_bucket_hamming_one_and_two_are_recalled` | RED |
| Ignore keyset `after` | `test_501_first_page_is_truncated_and_stable` | RED |
| Allow delegation replay | `test_delegation_replay_expiry_and_scope` | RED |
| Insert `INSERT INTO works` in import common | `test_provider_modules_do_not_insert_library_rows` | RED |
| Cache source mentions `DELETE FROM works` | `test_cache_eviction_source_cannot_delete_library_rows` | RED |

Second BREAK produced no new architecture-level hole. The 1001 continuation test is not used as a mutation target: disabling the cursor makes that loop non-terminating; the 501 first-page test is the bounded detector.

## Layer coverage

### Layer A — contract

- Paid ticket: `tests/test_nai_authorization.py`
- Remote identity + no-direct-write: `tests/test_library_writer_and_remote.py`
- Index cursor / anti-join / near-dup: `tests/test_gallery_index_continuation.py`
- Capability / delegation: `tests/test_capability_gateway.py`
- Mutation/fault source locks: `tests/test_mutation_and_faults.py`

### Layer B — integration

- Studio / char-swap HTTP 403 and authorize: `tests/test_char_swap_http_contract.py`, generate HTTP 403 in `test_nai_authorization.py`
- Butler still issues the same ticket (source + existing butler tests)
- Snapshot restore: `tests/test_gallery_snapshot.py`
- Schema v2: `tests/test_score_upgrades.py::test_schema_v2_records_migrations`
- `unknown` / `billing_uncertain` no auto-retry: `tests/test_generation_jobs.py`

### Layer C — synthetic E2E

- Online search → favorite (reference) → add to My Library → lineage → cache evict keeps row → provider outage keeps local library: `tests/test_online_library_e2e.py`
- 20× ticket issue/consume soak: `tests/test_synthetic_scale_and_soak.py`
- 10k metadata continuation completeness: same file
- 100k keyset scan &lt; 2s (Linux metadata only): same file

## Soak / flake

- Authorization consume×20: 0 unexpected successes on replay (failures==0 means no replay leak).
- Full suite twice: same 1202/68, no flake reruns.

## Evidence grade

| Claim | Grade |
|---|---|
| Paid ticket before transport | E3 (unit + HTTP + mutation) |
| Char-swap authorize + 403 | E3 |
| Index 501/1001 keyset | E3 |
| Unindexed/stale anti-join | E3 |
| Near-dup cross-bucket | E3 |
| Library writer / no-direct-write | E2/E3 (source guard + writer test; Pixiv still allow-listed) |
| Online → materialize → local survives outage | E2 synthetic |
| Capability allow/confirm/delegate/deny | E3 |
| 10k/100k | E2 Linux synthetic only |
| Windows / DPAPI / real NAI / real Pixiv | E0 — pending Windows |
