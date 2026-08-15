# Cloud PRs

## Integration

- Repository: h1neolzr7f/NaiXueZhang-Studio-Upgrade
- Branch: cursor/cloud-top-tier-integration-6d7e
- Base: main @ 008de38ad4dc6c8afbf0ec32ae411cd85685ac02
- Head: published via GitHub MCP; Draft PR https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pull/2
- Worker: Lead
- Scope: Phase 0 state, AGENTS.md, Windows doctor aliases, POSIX skips (D-003/D-007), butler/tooling skeleton, NAI compile lock tests
- Tests: cloud-safe pytest + scan_sensitive
- Benchmarks: none claimed
- Depends on: none
- Shared file conflicts: tests/test_startup_safety.py, tests/test_release_script_safety.py, tests/test_plaintext_at_rest.py (skip only)
- Windows pending: all of PENDING_LOCAL_WINDOWS.md
- Safe rollback: delete branch / close draft PR
- Lead review: approve for draft integration, not for main
- Publication: GitHub MCP (workspace git token is scoped to frozen v1.4 and returns 403)

## Pre-existing (do not treat as this plan)

- Upgrade PR #1 draft: Fix Pixiv provider presets... (`agent/github-front-door-polish`) — unrelated, do not merge from this Lead
- Studio v1.4 PR #2 draft: Mark v1.4 as frozen... — out of this integration
