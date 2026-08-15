# Cloud PRs

## Integration (this run)

- Repository: h1neolzr7f/NaiXueZhang-Studio-Upgrade
- Branch: cursor/cloud-top-tier-integration-f036
- Maps to: cloud/top-tier-integration
- Base: main @ 008de38ad4dc6c8afbf0ec32ae411cd85685ac02
- Draft PR: https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/3
- Worker: Lead
- Scope: Phase 0 continuation plus D-012 img2img/infill compile, PNG restore tests, additive gallery_index, kernel compile/index preview
- Tests: 1132 passed / 68 skipped / 1 pre-existing P1 quality-gate failure
- Benchmarks: synthetic in-memory only
- Depends on: worker branches listed below (files already reviewed onto this branch)
- Windows pending: PENDING_LOCAL_WINDOWS.md
- Safe rollback: close draft PR / delete branch
- Lead review: approve for draft integration, not for main

## Worker branches (independent, not merged to main)

| Worker | Branch | Draft PR | Deliverable | Lead review |
|---|---|---|---|---|
| W0 | cursor/cloud-w0-phase0-f036 | #7 | docs/top-tier-upgrade/W0_REVIEW.md | accepted onto integration |
| W1 | cursor/cloud-w1-nai-core-f036 | #8 | tests/test_nai_param_snapshots.py, W1_NAI_AUDIT.md | accepted onto integration |
| W2 | cursor/cloud-w2-gallery-f036 | #9 | GALLERY_INDEX_DESIGN.md | accepted onto integration |
| W3 | cursor/cloud-w3-agent-kernel-f036 | #6 | catalog_projection.py + tests | accepted onto integration |
| W4 | cursor/cloud-w4-quality-f036 | #5 | W4_QUALITY_AUDIT.md | accepted onto integration |

## Previous / unrelated

- Upgrade PR #2 draft: previous v1.4-bound integration (`cursor/cloud-top-tier-integration-6d7e`) — continued, do not discard
- Upgrade PR #1 draft: Pixiv provider presets — unrelated
