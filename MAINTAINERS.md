# Maintainers and governance

This document makes the current maintenance model for Nai学长工作室 explicit.

## Maintainer

- [@h1neolzr7f](https://github.com/h1neolzr7f) — primary maintainer

The primary maintainer owns the current `main` line, reviews issues and pull requests, coordinates releases, and maintains the project's security, privacy, and compatibility boundaries. There are no additional core maintainers at this time. Contributions are welcome under [CONTRIBUTING.md](CONTRIBUTING.md).

## Maintenance responsibilities

The maintainer is responsible for:

- triaging reproducible bug reports and feature proposals;
- reviewing changes for data loss, credential exposure, paid-request retry behavior, and path safety;
- keeping regression tests, sensitive-data scans, documentation, and release packaging in sync;
- publishing release notes, versioned Windows packages, and SHA-256 checksums;
- coordinating security reports through [SECURITY.md](SECURITY.md);
- documenting breaking changes and migration steps.

Public maintenance activity is visible in [commits](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/commits/main), [pull requests](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/pulls), and [releases](https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade/releases).

## Decision process

Small, reversible fixes may be merged after the relevant automated checks pass. Larger changes should begin with an issue that explains the user problem, data migration, compatibility impact, rollback path, and acceptance criteria.

Review priority is:

1. prevent credential disclosure, unauthorized access, and unrecoverable data loss;
2. preserve correct task state, especially when an external paid request has an unknown outcome;
3. keep existing local libraries and supported Windows workflows compatible;
4. require tests or reproducible validation for behavioral changes;
5. prefer maintainable, documented changes over feature breadth.

The primary maintainer makes final merge and release decisions. Decisions that change project scope, third-party-service boundaries, or local data handling should be documented in the pull request or repository documentation.

## Releases and support

The current maintained line and released versions are listed in [ROADMAP.md](ROADMAP.md). Release preparation follows [OPEN_SOURCE_CHECKLIST.md](OPEN_SOURCE_CHECKLIST.md). Support routes and information required for a useful report are described in [SUPPORT.md](SUPPORT.md).

The project does not promise a fixed response time. Security reports involving a credible vulnerability should use the private route in [SECURITY.md](SECURITY.md), not a public issue.

## Succession

If maintenance status changes, this document and the README will be updated. A future core maintainer must demonstrate sustained, constructive participation and agreement with the project's local-first, reproducible, and responsible-use principles before receiving merge or release authority.
