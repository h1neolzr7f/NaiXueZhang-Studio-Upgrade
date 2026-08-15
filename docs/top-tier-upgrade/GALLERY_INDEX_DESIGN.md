# Gallery Index Design

Worker: W2 (Gallery & Workflow 资产层，独立设计)  
Mode: `CLOUD_WEB`  
Base branch: `cursor/cloud-top-tier-integration-f036` @ `4d8dbea13eb166c4351c4e31f55ecc658bd40c6d`  
This document branch: `cursor/cloud-w2-gallery-f036`  
Repository: `h1neolzr7f/NaiXueZhang-Studio-Upgrade` only  
Manga / Phone / second task store: out of scope

This file is the only change in this Worker wave. It does not modify gallery production code, NovelAI client, Agent Runtime, `butler/store.py`, or `butler/workflow_runtime.py`.

---

## 0. C26 delivery

| Field | Value |
|---|---|
| Worker | W2 Gallery & Workflow asset layer |
| Role | Read-only audit + independent design |
| Unique repo | `h1neolzr7f/NaiXueZhang-Studio-Upgrade` |
| Baseline | `cursor/cloud-top-tier-integration-f036` @ `4d8dbea` |
| Worker branch | `cursor/cloud-w2-gallery-f036` |
| Allowed write | `docs/top-tier-upgrade/GALLERY_INDEX_DESIGN.md` only |
| Forbidden writes | `gallery_*.py`, `db.py`, `db_queries.py`, `search.py`, `nai_image_metadata.py`, `generated_gallery.py`, `routes/gallery.py`, `nai/`, `nai_api.py`, `butler/store.py`, `butler/workflow_runtime.py`, Lead docs (`DECISIONS.md`, `STATUS.md`, `OWNERSHIP.md`, `RUN_STATE.json`) |
| Production code changed | none |
| Tests this wave | none required (docs-only); existing `scripts/bench_gallery.py` remains synthetic |
| 10k/100k claim | forbidden; see §3.8 and WIN-010 |
| Merge to `main` | do not merge |
| Rollback | delete this branch |

---

## 1. Purpose and non-goals

### 1.1 Purpose

Design an additive Gallery index layer that can later support:

1. Incremental (dirty-set) indexing instead of full `rebuild_fts()` as the only path
2. Exact-duplicate and near-duplicate detection
3. Similar-image retrieval
4. Virtual albums that do not move files
5. Batch folder/album membership changes that always preview and can restore

Capability alignment (already scored, not rescored here):

| capability_id | current | target | this design |
|---|---:|---:|---|
| `search.fts_works_prompt` | 6.0 | 8.0 | incremental FTS + honest COUNT |
| `search.visual_similar` | 2.0 | 7.0 | local hashes first; semantic deferred |
| `ingest.local_drop_nai_only` | 7.0 | 8.0 | keep NAI-only gate; do not ingest Comfy/SD |

Competitor behavior studied, not copied: Infinite Image Browsing incremental index / similar / dup / virtual albums (`COMPETITOR_BASELINE.md`). Studio response remains NAI-only, local-first, additive routes.

### 1.2 Non-goals (this document and later implementation)

- Do not connect `Manga-Editor-Desu-NAI` or Phone.
- Do not create a second task / event store. Durable tasks stay in Lead-owned `butler/store.py`.
- Do not change `WorkRef={gallery_id,work_id}` or the existing `/api/ai_works_search` JSON shape (D-004).
- Do not add a second NovelAI HTTP client.
- Do not upload gallery bytes, prompts, or embeddings unless the user explicitly chooses a named cloud provider.
- Do not treat `scripts/bench_gallery.py` as a 10k/100k Windows number.
- Do not implement in this Worker wave. Implementation is a later v1.7 lease on W2 files after Lead accepts this design.

---

## 2. Frozen public interfaces

Keep these unchanged. New features attach beside them.

| Interface | Owner / file | Contract |
|---|---|---|
| `WorkRef` | `work_refs.py` | `{gallery_id, work_id}`; QQ / oversized IDs stay text at the API seam |
| `GET /api/ai_works_search` | `routes/gallery.py` | `page`, `page_size`, `items`, `total`, `gallery_id`; items keep current list_json fields |
| `Database.search_works` | `db_queries.py` | same kwargs and return keys |
| `parse_nai_image` | `nai_image_metadata.py` | accept only NovelAI provenance; reject Comfy |
| Three physical galleries | `gallery_catalog.py` | `site` / `codex` / `qqgroup`, each with its own DB + `images_dir` |

Additive routes (names reserved by this design, not implemented now):

- `GET /api/gallery/{gallery_id}/index/status`
- `POST /api/gallery/{gallery_id}/index/incremental`
- `GET /api/gallery/{gallery_id}/duplicates`
- `GET /api/gallery/{gallery_id}/similar`
- `GET|POST|PATCH|DELETE /api/gallery/{gallery_id}/albums`
- `POST /api/gallery/{gallery_id}/moves/preview`
- `POST /api/gallery/{gallery_id}/moves/commit`
- `POST /api/gallery/{gallery_id}/moves/{journal_id}/restore`

---

## 3. Read-only audit

Evidence is from Upgrade @ `4d8dbea` on the integration baseline. Line numbers are for that SHA.

### 3.1 `search.py` — query language only

`search.py` is a parser, not an index.

- Tokenizes quotes, parentheses, `OR`, and `-exclude`.
- Builds FTS5 `MATCH` strings; NAI prompts replace commas with spaces to avoid FTS5 syntax errors.
- Exclude terms are **not** compiled into FTS `NOT`. Callers apply `LIKE` filters later.

Gaps for a large library:

- Parentheses are parsed but group contents are flattened (`__group__` placeholder is unused). Nested boolean is incomplete.
- No field qualifiers (`model:`, `seed:`, `char:`). Facets live in `nai_tag_index.py`, not in this parser.
- No visual / semantic operators.

### 3.2 `db.py` — storage + full FTS rebuild

Schema already useful for an incremental layer:

| Existing column / object | Use later | Limit today |
|---|---|---|
| `work_images.source_sha256` | exact-byte identity | no unique index; drop import hashes bytes but does not always persist the digest on the row |
| `works.removed_status` | hide deleted without losing row | not a recycle journal |
| `works_fts` / `prompt_fts` / `prompt_work_fts` | keyword search | `rebuild_fts()` walks every work |
| `crawl_state` | flags such as `prompt_work_fts_ready` | also used as a group-index cache blob |
| WAL + reader connections | concurrent browse | writers still take `RLock` |

`rebuild_fts()` deletes both FTS tables and resyncs every work. That is correct for repair, too expensive as the default after a 100-file drop.

Per-work sync already exists: `_sync_work_fts`, `_sync_prompt_fts` (via `db_prompt_index.sync_prompt_fts`). Incremental index should call these for a dirty set, and keep `rebuild_fts` as the repair button.

### 3.3 `db_queries.py` — list search

`search_works` composes:

1. Gallery scope (`local` = NAI + `list_json`)
2. Forced `nai_only` at the HTTP layer
3. `nai_tag_facets` filters
4. Folder / account group from `list_json.group_key` / `category`
5. Works FTS + numeric id/author fallback
6. Prompt FTS (`prompt_work_fts` when ready, else `prompt_fts`)
7. Exclude via `LIKE` / `NOT EXISTS`
8. Time range and sort (including seeded random)

Honest limitations (do not paper over with cloud benches):

- Text queries set `total = None` (`skip_total` or `has_text_query`). Pagination works by `LIMIT/OFFSET` on ids, but the UI cannot show a trustworthy count.
- Exclude is table-scan `LIKE`, not FTS.
- Payload is two-step (ids then `IN (...)`) which is the right shape to keep. Do not join FTS rows into the sort.
- No similar / duplicate / album membership filter.

### 3.4 `nai_image_metadata.py` — ingest gate

Local-only parser. Accepts embedded NovelAI text, then PNG stealth. Rejects Comfy (`workflow` / `class_type` / software name). Requires a prompt. Stores `parser_version = qq-nai-v1+novelai-3d9c7b7`.

Index identity must include `parser_version`. A parser bump invalidates ingest cache rows even when `mtime_ns` is unchanged (QQ ingest already does this).

WebP publish (`gallery_asset_store.compress_image_for_storage`) drops PNG chunks. Metadata must stay in `ai_json` / `prompt_text` before any re-encode. Incremental visual hashes should prefer the stored original or the already-decoded RGB thumbnail, never re-parse WebP as NovelAI.

### 3.5 `gallery_*.py` and nearby asset files

| File | What it already does | What it is not |
|---|---|---|
| `gallery_catalog.py` | Three galleries; `WorkRef` gallery ids; group index cached in `crawl_state` | Not a virtual album store |
| `gallery_asset_store.py` | Path jail, WebP originals/thumbs, quota, orphan quarantine under `_orphans` | Not an index; quarantine is file-level, not membership undo |
| `gallery_cache.py` | Process TTL for read endpoints | Dies on restart; not durable |
| `gallery_guard.py` | Empty main gallery blocks crawler start | Unrelated to visual index |
| `gallery_maintenance.py` | Thumbs, tag rebuild, orphan reconcile, WebP migrate with rollback copy, snapshot | Full-library jobs; migrate is per-file transactional, folder merge is not |
| `gallery_snapshot.py` | Zip snapshot + `confirm=True` restore + maintenance lock | Whole-library disaster recovery, too heavy for one batch move |
| `gallery_audit_service.py` | Optional vision audit; **in-memory dHash** over the current candidate set (≤48 images, Hamming ≤2) | Not a persisted similar/dup index; `use_vision` already defaults false |
| `generated_gallery.py` | Directory mtime signature + persistent JSON cache | Separate generated tree; do not merge into site/codex/qq DBs |
| `routes/gallery.py` | Drop import (codex/qq), folder **merge**, search | Merge writes immediately; no preview, no journal, no restore |
| `qq_gallery_ingest.py` | `qq_ingest_files(source_id, file_size, mtime_ns, parser_version, status)` | Best existing incremental skip cache; site/codex drop has no equivalent table |
| `work_refs.py` / favorites / queue | Durable `WorkSelectionStore` JSON | Closest existing “virtual set”; not queryable albums |
| `web/shared/gallery-virtual.js` | IntersectionObserver thumb load/unload | Virtual **scroll**, not virtual **albums** |
| `knowledge_catalog.py` | Markdown FTS5; explicitly no embedding model | Pattern to copy: local FTS first, semantic only if measured misses justify it |

### 3.6 Incremental pieces that already exist (reuse, do not fork)

1. **QQ ingest cache** — skip unchanged `(source_id, size, mtime_ns, parser_version)`.
2. **Drop stable id** — `stable_work_id("drop", sha256(bytes))` so the same file maps to the same `work_id`.
3. **Per-work FTS sync** — already called from upsert/save/merge.
4. **Generated-dir signature** — `(count, latest_mtime, dir_mtime_ns)` cheap skip.
5. **Thumbnail mtime** — rebuild only when original is newer.
6. **Pixiv intake `source_sha256`** — byte identity on collected pages.

Missing: a **cross-gallery dirty journal**, a **persisted perceptual hash table**, and a **move journal**.

### 3.7 Gaps that this design fills

| Gap | User-visible effect | Design answer |
|---|---|---|
| Full FTS rebuild as the mental model | Import 100 files feels like reindex-all | Dirty set + per-work sync; rebuild is repair |
| No exact-dup index | Same PNG dropped twice looks like one work (good) but Pixiv + drop copies are invisible | `image_identity` unique on sha256 per gallery |
| No near-dup index | Seed variations / recompress / crop not grouped | Local dHash + pHash tables |
| No similar API | ROADMAP “视觉智能” unchecked | Additive `/similar` on local hashes; embedding later |
| Folders are physical metadata | Merge rewrites `list_json` in place | Virtual albums are membership; physical move is a journaled operation |
| Folder merge has no preview/restore | Accidental merge is permanent except whole-library snapshot | Move journal with preview → commit → restore |
| Cloud vision already exists as opt-in audit | Risk of silent upload if similar-search “just works” | Default `embedding.provider=local_none`; cloud requires explicit settings + confirm |

### 3.8 `scripts/bench_gallery.py` is not a 10k/100k claim

The script builds an in-memory list and filters with `parse_query`. It does not open SQLite, does not touch `data/aitag.db`, and does not measure FTS, COUNT, thumbnails, or disk.

Required disclaimer on any number from that script:

> synthetic in-memory micro-bench; not a Windows 10k/100k claim; see `BENCHMARKS.md` and `PENDING_LOCAL_WINDOWS` WIN-010.

Real incremental-100 / keyword / similar / thumbnail benches stay on Windows with recorded CPU/RAM/SSD and a real library.

---

## 4. Design principles

1. **Local-first.** Default path never leaves the machine. No API key ⇒ no outbound embedding.
2. **Additive schema.** New tables; no rewrite of `works` / `work_images` primary keys.
3. **Per-gallery isolation.** `site`, `codex`, `qqgroup` keep separate DBs. Cross-gallery similar is a later opt-in query that unions `WorkRef`s, never merges files.
4. **Identity is a tuple.** `(gallery_id, work_id, page_index)` is the image key. `WorkRef` stays two-field; page is a query argument.
5. **Parser version is part of freshness.** Same bytes + new parser ⇒ re-extract metadata, reuse hashes if pixels unchanged.
6. **Destructive membership changes are journals.** Preview is mandatory. Restore is the inverse of the journal, not “hope a zip snapshot exists”.
7. **NAI-only ingest stays closed.** Indexing never becomes a back door for Comfy/SD.
8. **Butler does not get a second task DB.** If a long index job needs progress, emit events through existing Lead interfaces later; this design stores only gallery-local job rows in `crawl_state` / a small `gallery_index_jobs` table.

---

## 5. Incremental index

### 5.1 Layers

```
disk file
  → identity (sha256, size, mtime_ns, path)
    → metadata (parse_nai_image / existing ai_json)
      → text indexes (works_fts, prompt_fts, prompt_work_fts, nai_tag_facets)
        → visual indexes (dhash, phash)          [local, default on after first enable]
          → embedding index                      [off; local ONNX or cloud only if chosen]
```

Each layer has its own `index_revision` and can be dirty independently. A WebP migrate changes path + maybe pixels; metadata layer stays clean if `ai_json` is untouched.

### 5.2 New table (additive, per gallery DB)

```sql
CREATE TABLE IF NOT EXISTS gallery_index_files (
    image_key TEXT PRIMARY KEY,          -- "{work_id}:{page_index}"
    work_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    file_size INTEGER,
    mtime_ns INTEGER,
    source_sha256 TEXT,
    parser_version TEXT,
    text_rev INTEGER NOT NULL DEFAULT 0,
    visual_rev INTEGER NOT NULL DEFAULT 0,
    embed_rev INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_index_sha
    ON gallery_index_files(source_sha256);
CREATE INDEX IF NOT EXISTS idx_gallery_index_dirty_text
    ON gallery_index_files(text_rev);
```

Constants live in code, not user config:

- `TEXT_INDEX_REV = 1`  — bump when FTS/facet rules change
- `VISUAL_INDEX_REV = 1` — bump when hash algorithm/size changes
- `EMBED_INDEX_REV = 1`  — bump when embedding model id changes

Dirty predicate:

```
row missing
OR file_size/mtime_ns/sha256 mismatch vs disk
OR parser_version != current
OR text_rev < TEXT_INDEX_REV
OR (visual enabled AND visual_rev < VISUAL_INDEX_REV)
OR (embed enabled AND embed_rev < EMBED_INDEX_REV)
```

### 5.3 Scan algorithm (default after drop / QQ ingest / Pixiv persist)

1. Collect candidate keys from the write path (known `work_id`s) **or** walk `work_images` where `downloaded=1`.
2. Stat those files only. Do not hash if `(size, mtime_ns)` matches and `source_sha256` is present.
3. Hash when size/mtime missing or mismatch. Compare to stored sha256.
4. For each dirty key: sync FTS + facets (existing functions). Optionally compute visual hashes.
5. Write `gallery_index_files` in the same DB transaction as FTS when possible.
6. Refresh `group_index:{gid}` only if any `group_key` / `category` changed.

Never use “reindex entire library” as the import tail. Expose repair:

- `incremental` — dirty set only (default)
- `repair_text` — `rebuild_fts` + facet rebuild
- `repair_visual` — recompute hashes for all local files
- `repair_embed` — only if embedding is explicitly enabled

### 5.4 Triggers (when implemented)

| Event | Dirty set |
|---|---|
| `import-drop` accepted files | those `work_id`s |
| QQ ingest new/changed `source_id` | those works |
| Pixiv persist pages | those pages |
| WebP migrate | path + sha256 + visual; text clean |
| Thumbnail rebuild | visual optional (hash from thumb is last resort) |
| Folder merge / album commit | membership only; files not dirty |
| Parser version bump | all rows with old `parser_version` |
| User clicks “修复索引” | repair_* |

### 5.5 Status payload

`GET /api/gallery/{gallery_id}/index/status` (additive):

```json
{
  "gallery_id": "codex",
  "works": 0,
  "images_local": 0,
  "text_dirty": 0,
  "visual_dirty": 0,
  "embed_dirty": 0,
  "embed": {"provider": "local_none", "model": null, "outbound": false},
  "last_incremental_at": null,
  "notes": "Counts are SQLite metadata, not a Windows 10k/100k bench."
}
```

---

## 6. Duplicates

Two classes. Do not collapse them in the UI.

### 6.1 Exact duplicate (byte identity)

Key: `source_sha256` (SHA-256 of the file bytes **before** WebP recompress when still available; after migrate, hash of the stored WebP).

Group: same sha256, same gallery, different `image_key` **or** same sha256 across galleries (report as `WorkRef` pairs, do not auto-merge galleries).

Drop import already maps same bytes to the same `work_id` via `stable_work_id("drop", digest)`. Exact-dup UI is still needed for:

- Pixiv collect vs later local drop of the same PNG
- Same file in two drop folders after a copy (if ids diverge)
- QQ ingest vs drop

Action policy:

- Detect and show. Do not auto-delete.
- “Keep one” is a journaled move to `_orphans` or `removed_status`, never silent unlink.
- Preview lists every `WorkRef` + page + folder + byte size.

### 6.2 Near duplicate (perceptual)

Reuse the audit dHash (8×9 grayscale, Hamming ≤2 is “same” in the current batch). Persist it and add pHash (DCT 32→8, Hamming thresholds below).

| Kind | Algorithm | Default threshold | Meaning |
|---|---|---|---|
| exact | SHA-256 | 0 | same bytes |
| near-same | dHash 64-bit | Hamming ≤ 4 | recompress / color profile |
| near-same | pHash 64-bit | Hamming ≤ 8 | mild crop/scale |
| similar | pHash or local embed | Hamming ≤ 12 or cosine ≥ 0.92 | same composition, different seed |

Thresholds are defaults, not 10k-validated. WIN-010 must re-tune on a real library. Do not advertise “IIB-class similar” until that bench exists.

Storage:

```sql
CREATE TABLE IF NOT EXISTS gallery_image_hashes (
    image_key TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    sha256 TEXT,
    dhash INTEGER,
    phash INTEGER,
    width INTEGER,
    height INTEGER,
    algo_rev INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_hashes_sha ON gallery_image_hashes(sha256);
CREATE INDEX IF NOT EXISTS idx_gallery_hashes_dhash ON gallery_image_hashes(dhash);
```

Query strategy at Studio scale (target later: 10k–100k on Windows, not claimed now):

1. Exact: index lookup on sha256.
2. Near: bucket by top 16 bits of dHash/pHash, then Hamming in the bucket. Avoid O(n²) in Python over the whole library.
3. Do not load PIL for files whose hash row is fresh.

`gallery_audit_service` in-memory dHash remains a **quality audit** helper. The persisted table is the product index. Do not call `chat_json` from duplicate detection.

---

## 7. Similar images

### 7.1 Default: local visual neighbors

`GET /api/gallery/{gallery_id}/similar?work_id=&page_index=&limit=24`

- Resolve `WorkRef` + page.
- If hash row missing, compute on demand for that one image, then search.
- Return `{items:[{gallery_id, work_id, page_index, distance, kind}], query: WorkRef}`.
- `kind` is `phash` | `dhash` | `prompt` | `embed`.
- Prompt fallback: existing FTS on the work’s prompt tokens (already local). Useful when hashes are not built yet.

Frozen search JSON is untouched. The gallery UI can open similar as a side panel.

### 7.2 Prompt-similar (local, cheap)

Optional `kind=prompt`: `build_prompt_fts_query` on the source prompt, exclude the source `work_id`. This is not visual similar. Label it “咒语相近” so users do not think it is a vision model.

### 7.3 Semantic / embedding (off by default)

See §10. Similar API may return `embed` rows only when `embed.provider != local_none` and the user enabled that provider in settings **and** the request repeats `embed=1`.

---

## 8. Virtual albums

### 8.1 Why not reuse folders

Current folders (`group_key` / `category` on `list_json`) are **physical classification** for drop/QQ. Merge rewrites every matching work. A work has one folder.

Virtual albums are **many-to-many membership**:

- One work can be in “待超分”, “角色A”, and “本周发布候选”.
- Removing from an album does not move the file and does not change `group_key`.
- Deleting an album drops membership rows only.

Favorites and the production queue stay as they are (`WorkSelectionStore`). Albums are queryable, named, and can be smart (rule-based).

### 8.2 Types

| Type | Definition | Recompute |
|---|---|---|
| `manual` | User pinned `WorkRef`s | never |
| `smart` | Frozen rule JSON: FTS q/prompt, facets, folder, dup-group, time_range | on open if `rule_rev` or index rev changed |
| `dup_stack` | System album per exact/near group | when hash table changes |

Smart albums store the rule, not a copied result set, except a cache of ids with `cached_at` + `text_rev`.

### 8.3 Schema

```sql
CREATE TABLE IF NOT EXISTS gallery_albums (
    album_id TEXT PRIMARY KEY,
    gallery_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,              -- manual | smart | dup_stack
    rule_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gallery_album_items (
    album_id TEXT NOT NULL,
    work_id INTEGER NOT NULL,
    page_index INTEGER,
    added_at TEXT NOT NULL,
    source TEXT NOT NULL,            -- user | smart | dup
    PRIMARY KEY (album_id, work_id, page_index)
);
```

`gallery_id` on the album is the home library. Cross-gallery albums are forbidden in v1. Users can favorite across galleries already.

### 8.4 Listing

`GET /api/ai_works_search` gains **no** new required fields. Optional later additive query `album_id=` may be accepted only if Lead agrees it does not break clients that ignore unknown kwargs. Safer: albums have their own list endpoint that **reuses** `search_works` id pagination internally and returns the same item shape plus `album_id`.

---

## 9. Batch move: preview and restore (mandatory)

This applies to:

- Physical folder merge / move (today’s `/folders/merge`)
- Album add/remove of many works
- “Keep one duplicate” quarantine
- Cross-folder drop of existing works

Today `_merge_gallery_folders` updates `list_json` / `detail_json` / tags / FTS and commits. There is no preview and no inverse. Whole-library `GallerySnapshotManager.restore(confirm=True)` is the only undo, and it is the wrong granularity.

### 9.1 Three-step protocol

```
preview  →  user confirms  →  commit journal  →  apply  →  restore(journal_id)
```

No apply without a preview token. Preview is read-only and expires (default 15 minutes). Commit without a valid preview id is rejected.

### 9.2 Preview payload

```json
{
  "preview_id": "mv_...",
  "gallery_id": "codex",
  "op": "folder_move",
  "expires_at": "...",
  "from": {"kind": "folder", "key": "group:A"},
  "to": {"kind": "folder", "key": "group:B"},
  "would_touch": 12,
  "samples": [{"work_id": "1", "title": "...", "from": "A", "to": "B"}],
  "irreversible_without_journal": true,
  "files_rewritten": false
}
```

`files_rewritten=false` for metadata-only folder/album ops. `true` only when files would be renamed or quarantined. If `true`, preview must list byte sizes and refuse when quota/disk check fails (`GalleryAssetStore.has_capacity`).

### 9.3 Journal

```sql
CREATE TABLE IF NOT EXISTS gallery_move_journal (
    journal_id TEXT PRIMARY KEY,
    preview_id TEXT NOT NULL,
    gallery_id TEXT NOT NULL,
    op TEXT NOT NULL,
    state TEXT NOT NULL,             -- previewed | committed | restored | failed
    request_json TEXT NOT NULL,
    inverse_json TEXT NOT NULL,
    touched INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    committed_at TEXT,
    restored_at TEXT
);
```

`inverse_json` is a complete undo script: previous `group_key` / `category` / tags / caption / album membership / relative paths / `removed_status` per `work_id`. Apply and restore run in one SQLite transaction. File quarantines use `os.replace` into `_orphans/journal_id/` so restore is `os.replace` back, same as migrate rollback.

### 9.4 Rules

- Restore requires `confirm=true` (same spirit as snapshot restore).
- Restore of a later journal that overlaps works is rejected (`conflict`); user restores newest first.
- Butler / Agent tools that move or delete must emit `WorkflowRequest` (Lead-owned runtime). This design only defines the gallery journal; it does not wire tools.
- Existing `/folders/merge` stays until an implementing PR replaces it with preview+commit **in the same change** that updates the drop-folder UI. Do not leave a silent dual path.

### 9.5 What “batch move” must never do

- Move files across the three gallery roots without an explicit copy+ingest (NAI parse again).
- Delete originals on commit of a metadata move.
- Call snapshot zip as a substitute for the journal.

---

## 10. Embedding and cloud policy

### 10.1 Default

```
embed.provider = local_none
embed.outbound = false
```

Similar and duplicate features must work with **only** SHA-256 + dHash + pHash + FTS. That is the v1.7 acceptance bar for `search.visual_similar` moving from 2.0 toward 7.0.

`knowledge_catalog.py` already states the product rule: do not load an embedding model until measured misses justify it. Gallery follows the same rule.

`gallery_audit_service.run_gallery_audit(..., use_vision=False)` is the precedent: vision is explicit. Similar search must not flip that default.

### 10.2 Local embedding (optional, still on-box)

Allowed later if WIN-010 shows hash neighbors fail (same character, different costume/composition):

| Field | Rule |
|---|---|
| Provider id | `local_onnx` |
| Model | user-selected file under `data/models/` (allow-list extension `.onnx`) |
| Device | CPU / DirectML on Windows; never required for browse |
| Outbound | false |
| First run | settings toggle + disk/RAM estimate + confirm |
| Failure | disable provider, keep hash index; do not retry as cloud |

Do not vendor a GPL embedder. MIT/Apache ONNX runtime is acceptable; model license must be recorded in settings.

### 10.3 Cloud embedding (explicit choice only)

Forbidden unless **all** of the following are true:

1. Settings: `embed.provider` is a named cloud (`openai` / `other` — exact vendor list is a later Lead decision).
2. User pasted a key into the existing secret store (DPAPI on Windows). No key in repo.
3. UI copy: “将把缩略图或向量发往 {provider}”. Checkbox `I understand this leaves this machine`.
4. Request flag `embed=1` on that one similar/index call. No background sweep.
5. Batch size cap (e.g. 32 thumbs / call). No silent full-library upload.
6. Ledger: record `provider`, `image_count`, `bytes`, `at` in a local JSONL under `data/gallery_embed_audit.jsonl`. No image bytes in the log.
7. Paid/uncertain semantics follow existing generation rules: unknown is not “free retry”. This Worker does not implement billing.

If any check fails, the API returns `embed_not_enabled` and hash results only.

### 10.4 What is never sent

- Full originals
- NAI token / Pixiv credentials
- Prompt text, unless the user also enables `embed.include_prompt` (default false)
- Site library sweep while browsing

---

## 11. Additive HTTP (implement later)

All routes require the existing loopback / session rules. `nai_only` remains enforced.

| Method | Path | Body / query | Result |
|---|---|---|---|
| GET | `/api/gallery/{id}/index/status` | | dirty counts |
| POST | `/api/gallery/{id}/index/incremental` | `{mode:"incremental"\|"repair_text"\|"repair_visual"}` | job summary |
| GET | `/api/gallery/{id}/duplicates` | `kind=exact\|near`, paging | groups of `WorkRef` |
| GET | `/api/gallery/{id}/similar` | `work_id`, `page_index`, `embed=0` | neighbor items |
| GET | `/api/gallery/{id}/albums` | | album list |
| POST | `/api/gallery/{id}/albums` | `{title, kind, rule_json}` | album |
| POST | `/api/gallery/{id}/moves/preview` | `{op, from, to, work_refs?}` | preview |
| POST | `/api/gallery/{id}/moves/commit` | `{preview_id, confirm:true}` | journal |
| POST | `/api/gallery/{id}/moves/{journal_id}/restore` | `{confirm:true}` | inverse |

`/api/ai_works_search` JSON keys stay stable. Clients that only know search keep working.

---

## 12. Implementation phases (after Lead accepts; not this PR)

| Phase | Ships | Acceptance | Depends |
|---|---|---|---|
| A | `gallery_index_files` + incremental FTS/facet sync on drop/QQ/Pixiv | Import N files only dirties N; repair still available | existing `_sync_*` |
| B | Exact sha256 duplicate groups + UI list | Same file in two sources appears as one group; no auto-delete | A |
| C | Persist dHash/pHash + `/similar` | Neighbors from local hashes; no network | B, WIN-010 to tune |
| D | Move preview/commit/restore; migrate folder merge UI | Accidental merge undoable without zip snapshot | A |
| E | Manual + smart virtual albums | Membership does not move files | D |
| F | Optional local ONNX embed | Off by default; explicit toggle | C + model license |
| G | Cloud embed | All §10.3 checks; audit log | F + user key; never in Cloud CI |

Phase A–D are the honest path to raise `search.fts_works_prompt` and start `search.visual_similar`. F/G stay deferred (`CAPABILITY_MATRIX` already says defer semantic).

---

## 13. Tests and benches (when implementing)

Cloud-safe (no user library):

- Unit: dirty predicate; sha256 group; Hamming; preview token expiry; restore inverse on a temp SQLite.
- Keep using `scripts/bench_gallery.py` only as a parser micro-bench with the synthetic disclaimer.

Windows (WIN-006, WIN-010):

- Junction / offline drive: incremental scan fail-closed, no silent identity rewrite.
- Real 1k / 10k import, incremental 100, keyword p95, similar p95, thumbnail scroll.
- Record OS, CPU, RAM, SSD, image count. Do not delete a failing bench.

Do not add production code in order to make a cloud bench look like 10k.

---

## 14. Proposed decisions (Lead owns `DECISIONS.md`)

W2 does not edit `DECISIONS.md`. Suggested entries:

| Id (suggested) | Choice |
|---|---|
| D-G1 | Incremental index is dirty-set + per-work FTS; `rebuild_fts` is repair only |
| D-G2 | `/api/ai_works_search` unchanged; dup/similar/album/move are additive |
| D-G3 | Default embedding provider is `local_none`; cloud requires settings + per-request `embed=1` |
| D-G4 | Batch folder/album/dup-quarantine must preview and journal-restore |
| D-G5 | `scripts/bench_gallery.py` must never be cited as 10k/100k |
| D-G6 | Virtual albums are membership tables; physical `group_key` remains drop/QQ folders |

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Dual folder-merge paths | Replace merge in the same UI PR as journal |
| Hash false positives | Show distance; user confirms quarantine |
| Parser bump rewrites ingest | Version in dirty predicate; QQ already does this |
| Embed accidental upload | Default off; fail closed; audit log |
| Large COUNT still slow | Keep `total=None` on text search until a dedicated count plan exists; do not fake totals |
| Cross-gallery id collision | Always carry `gallery_id` (`WorkRef`) |
| Lease conflicts | This wave writes only this markdown file |

---

## 16. Rollback

- This wave: `git checkout cursor/cloud-top-tier-integration-f036`; delete `cursor/cloud-w2-gallery-f036`.
- Later implementation: feature flags default off; `DROP TABLE` of the four new tables is safe if no production writer has shipped; file quarantine journals remain under `_orphans/`.
- Do not merge this branch to `main` from W2.

---

## 17. C26 handoff to Lead

```
WORKER: W2
REPO: h1neolzr7f/NaiXueZhang-Studio-Upgrade
BASE: cursor/cloud-top-tier-integration-f036 @ 4d8dbea13eb166c4351c4e31f55ecc658bd40c6d
BRANCH: cursor/cloud-w2-gallery-f036
FILES: docs/top-tier-upgrade/GALLERY_INDEX_DESIGN.md
PRODUCTION_CODE: unchanged
NAI_CLIENT: untouched
AGENT_RUNTIME: untouched
butler/store.py: untouched
workflow_runtime.py: untouched
MANGA: not connected
SECOND_TASK_STORE: not created
BENCH: scripts/bench_gallery.py remains synthetic in-memory; not 10k/100k
TESTS: docs-only wave; no new pytest required
MERGE_MAIN: no
LEAD_ACTION: review design; cherry-pick or merge this file onto the integration branch; do not start gallery production edits until Phase A is scheduled
```
