# Autonomous decisions

## AD-001 Ticket before transport

Non-free compile results require a one-time HMAC ticket bound to action, copies, manifest hash, and cost-relevant payload hash. Authorization runs before token-pool wait and before NovelAI HTTP.

## AD-002 Butler confirmation issues the same ticket

Butler `generate_image` / batch workflows already have a user confirmation. They issue a NAI ticket at confirm time and pass it into `start_batch`. No second job lifecycle.

## AD-003 Library writer is additive

QQ / drop / Codex go through `materialize_asset`. Pixiv intake keeps receipts and is allow-listed until a later wrap. Site crawler SQL stays in `db.py` / `db_crawler_writes.py`.

## AD-004 Index continuation is keyset, not offset

`(work_id, page_index)` cursor commits with the upsert. Reconciliation uses source↔index anti-joins and never treats “not in this 500 page” as stale.

## AD-005 Near-dup bands

`t+1` non-overlapping bands on both dHash and pHash. Pair grouping kept. Single high-bit bucket is no longer the candidate generator.

## AD-006 Lifecycle is facts

Remote / Cached / Materialized are derived. Cache eviction cannot delete materialized rows.

## AD-007 Capability ≠ Persona

Orchestrator is deny-all for execution. Service persona cannot generate or delete. Cross-domain work uses short-lived delegation tokens.

## AD-008 Retry reuses the frozen job, not a caller flag

`start_batch(..., _paid_authorized=True)` is ignored. Reuse happens only when `_retry_of` is a persisted job that was already `paid_authorized` and the remaining targets' fingerprints are a subset of that job. Mutated comments fail closed.

## AD-009 Online lives on classic `/`

The React workspace gallery is not the product `/` shell (`/app` still redirects). Online / My Library is a「在线发现」control on the classic atlas source bar. Primary nav stays 8 items.

## AD-010 Tickets are process-local

HMAC secret and consumed nonces live in process memory. Restart drops unused tickets. That matches the single-process local app. Unused tickets are not durable across crash.
