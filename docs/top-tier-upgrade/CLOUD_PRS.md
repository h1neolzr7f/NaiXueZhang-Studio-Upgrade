# Cloud PRs

## Integration (this run)

- Repository: h1neolzr7f/NaiXueZhang-Studio-Upgrade
- Branch: cursor/cloud-top-tier-integration-f036
- Maps to: cloud/top-tier-integration
- Base: main @ 008de38ad4dc6c8afbf0ec32ae411cd85685ac02
- Head: pending this commit
- Worker: Lead (continues W0–W4 work on one integration branch)
- Scope: continue Phase 0 state; Cloud Environment draft; NAI unknown-field reporting; tooling timeout/cancel; gallery micro-bench; fault injection; Windows script static check
- Tests: cloud-safe pytest + scan_sensitive + bench_gallery
- Benchmarks: synthetic in-memory only; no 10k/100k claim
- Depends on: previous `cursor/cloud-top-tier-integration-6d7e` content
- Shared file conflicts: none with `main` beyond the continued tree
- Windows pending: all of PENDING_LOCAL_WINDOWS.md
- Safe rollback: delete branch / close draft PR
- Lead review: approve for draft integration, not for main

## Previous (continued, do not discard)

- Upgrade PR #2 draft: Phase 0 top-tier upgrade state and safe Wave 2 skeleton (`cursor/cloud-top-tier-integration-6d7e`)

## Pre-existing (do not treat as this plan)

- Upgrade PR #1 draft: Fix Pixiv provider presets... (`agent/github-front-door-polish`) — unrelated, do not merge from this Lead
