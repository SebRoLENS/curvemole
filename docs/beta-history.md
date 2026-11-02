# Published beta history

Generated from beta tags and the GitHub release catalog (when available). Beta run numbers may have gaps. Each section describes changes between consecutive published betas, or since the previous stable release. The cumulative stable-cycle history is in `CHANGELOG.md`.

## [1.2.0-beta.88](https://github.com/SebRoLENS/curvemole/releases/tag/v1.2.0-beta.88) — published 2026-11-02

Changes since `v1.1.1-beta.50` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.1-beta.50...v1.2.0-beta.88)).

### Added

- Add a Shortcuts menu with separate mouse and keyboard references. ([`67a30d61`](https://github.com/SebRoLENS/curvemole/commit/67a30d6165da14304d245a598a1578a6dbc46c09))

### Changed

- Backfill beta-cycle changes from stable 1.1.0 through current testing. ([`3a52b91c`](https://github.com/SebRoLENS/curvemole/commit/3a52b91c47d8b2cae67f94fecd639c09dac30577))
- Backfill all nine published beta releases with actual commit histories. ([`780de88d`](https://github.com/SebRoLENS/curvemole/commit/780de88d20a673f33e11634eed86ce5472293804))
- Exclude GitHub release tooling metadata from user-facing feature summaries. ([`28722969`](https://github.com/SebRoLENS/curvemole/commit/2872296910a2eb42cd1ccba24479d96f51280e00))
- Synchronize clean cumulative feature and fix history through current beta. ([`10b3634d`](https://github.com/SebRoLENS/curvemole/commit/10b3634d150a6703aa438b0273a3d2dface5d448))
- Render historical stable releases on What’s New with curated 1.1.0 backfill. ([`ae59b894`](https://github.com/SebRoLENS/curvemole/commit/ae59b89433d59deaea5d6d46a0d5a69a4774b983))
- Show stable release archive in What’s New from 1.0.0 onward. ([`cabbd7ad`](https://github.com/SebRoLENS/curvemole/commit/cabbd7ad72bd9fc2ca519874359c47ab4092ce85))
- Style chronological What’s New release archive on desktop and mobile. ([`cbfbeef0`](https://github.com/SebRoLENS/curvemole/commit/cbfbeef0e94237fd557d3eefcd84482ff8d5ff92))
- Swap double-click view scopes: left for unmasked points, right for all points. ([`67a30d61`](https://github.com/SebRoLENS/curvemole/commit/67a30d6165da14304d245a598a1578a6dbc46c09))
- Prepare 1.2.0 beta with explicit shortcut additions and restored categories. ([`49760681`](https://github.com/SebRoLENS/curvemole/commit/49760681873e84ea83f3f035ef4f63919ed23bd7))

### Fixed

- Fix shortcut reference tests for native macOS key labels. ([`c3e0d745`](https://github.com/SebRoLENS/curvemole/commit/c3e0d745ab48f25a1c40bb39a7f1b028127a8079))
- Fix scientific audit findings and publish tested beta corrections. ([`d72828c2`](https://github.com/SebRoLENS/curvemole/commit/d72828c25066bee8490b43ace2ec3b32f1972ccd))
- Handle Windows parser recursion and native macOS shortcut checks. ([`f3ac6c06`](https://github.com/SebRoLENS/curvemole/commit/f3ac6c068fe7826cebbcf24e1925d67cc9b86f7e))

### Documentation

- Document missing 1.1.0 stable changes from its published Git history. ([`bbc2e93c`](https://github.com/SebRoLENS/curvemole/commit/bbc2e93cee5339f201eb7a556042d09e20413dfd))
- Repair website history renderer and build dated stable archive safely. ([`94a41ff8`](https://github.com/SebRoLENS/curvemole/commit/94a41ff8e864b3fdffcf82d19038f70e8ea6276a))
- Document historical stable What’s New publication behavior. ([`d5c8b9f5`](https://github.com/SebRoLENS/curvemole/commit/d5c8b9f5d61a0ec881b7a582bb97f1a9e1f009d9))
- Repair website generator syntax and remove duplicated trailing content. ([`23b9f54b`](https://github.com/SebRoLENS/curvemole/commit/23b9f54b7e238b719b832b7564711f194aa1b883))

## [1.1.1-beta.50](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.1-beta.50) — published 2026-10-30

Changes since `v1.1.1-beta.20` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.1-beta.20...v1.1.1-beta.50)).

### Added

- Add provider-independent file handoff protocol. ([`a650228c`](https://github.com/SebRoLENS/curvemole/commit/a650228c73adb576ebbb571321da2b34813ec91d))

### Changed

- Coordinate shared-folder transfer and lock ownership in desktop. ([`fd8c402d`](https://github.com/SebRoLENS/curvemole/commit/fd8c402dc0e346b0f4ed59caf50483ceacc3c650))
- Transfer project lock to Save As target and prevent concurrent overwrites. ([`38b552ca`](https://github.com/SebRoLENS/curvemole/commit/38b552ca5fa14216f23a6b01de9927eff999c944))

### Fixed

- Harden project lock identities and guarded commit. ([`d25eb73f`](https://github.com/SebRoLENS/curvemole/commit/d25eb73f0ffba35584d1fd065cd9634766c9429d))
- Avoid same-host handoff prompts and preserve editability if reply fails. ([`32218baf`](https://github.com/SebRoLENS/curvemole/commit/32218bafd23c5415a4142acbc7dc4169c6b62caf))
- Guard Save As destinations and gracefully handle transfer errors. ([`26945515`](https://github.com/SebRoLENS/curvemole/commit/26945515fdfd602c3cc6f98f207a977dac24ff7f))
- Handle concurrent requests and unresponsive remote sessions safely. ([`3dcb1428`](https://github.com/SebRoLENS/curvemole/commit/3dcb1428da4b0d05a4d3a9db937d4bf5e2223d45))
- Preserve accepted transfer even if rejecting others fails. ([`1dc2706a`](https://github.com/SebRoLENS/curvemole/commit/1dc2706a9aec914aa15d1f3e29697304c08cce50))
- Fix project-locking documentation formatting. ([`88831288`](https://github.com/SebRoLENS/curvemole/commit/88831288eb1a9e7fde7555b3a16e25fdc7a8dfd2))

### Documentation

- docs: include CurveMole RRID in scholarly metadata, website and app exports. ([`b680a5c5`](https://github.com/SebRoLENS/curvemole/commit/b680a5c576dd6a6a8576f4fbf84cf2c7d818e623))
- docs: add all-versions Zenodo Concept DOI to software, exports, manuals and website. ([`44e6c4d7`](https://github.com/SebRoLENS/curvemole/commit/44e6c4d756bcb9a2545a79e45e63aa311a3ae471))
- Unify software citations across documentation and website. ([`12fe9551`](https://github.com/SebRoLENS/curvemole/commit/12fe9551af2940d32aedca67ab86b17a6a86c3eb))
- Explain citation roles in About and analysis exports. ([`2cf2a621`](https://github.com/SebRoLENS/curvemole/commit/2cf2a621f42612cb473dd292048c89f4a3450b8b))
- Include citation generator in isolated promotion tests. ([`2977a143`](https://github.com/SebRoLENS/curvemole/commit/2977a1431b290a063f3470468102d959d7bfb3fa))
- Add consent-gated CurveMole website analytics. ([`3459c3a3`](https://github.com/SebRoLENS/curvemole/commit/3459c3a3ceafce260372f904f8986fd527fcc6d4))
- Organize website pages and add sitemap. ([`21de68e7`](https://github.com/SebRoLENS/curvemole/commit/21de68e7998429d2d9ce7edbc166acb484c0f2e4))

## [1.1.1-beta.20](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.1-beta.20) — published 2026-10-29

Changes since `v1.1.0-beta.17` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.0-beta.17...v1.1.1-beta.20)).

### Changed

- Publish current stable automation documentation. ([`fee4bcb4`](https://github.com/SebRoLENS/curvemole/commit/fee4bcb403bce64c47427b37ffdae42c5ee7d832))

### Fixed

- Fix batch YAML workflow automation for beta 1.1.1. ([`f3fc2ccd`](https://github.com/SebRoLENS/curvemole/commit/f3fc2ccde5841a4b523161db8c9fc2e6dc389945))

### Documentation

- Document Python scripting and YAML automation audits. ([`2b867074`](https://github.com/SebRoLENS/curvemole/commit/2b867074ef3811ae478e3d2fdd4d23f3d90782b5))

## [1.1.0-beta.17](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.0-beta.17) — published 2026-10-27

Changes since `v1.1.0-beta.16` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.0-beta.16...v1.1.0-beta.17)).

### Fixed

- Fix all beta audit findings and consolidate fit and rendering transactions. ([`6dfce6d5`](https://github.com/SebRoLENS/curvemole/commit/6dfce6d59749e52295ddad504b9cf316ecb228bf))

## [1.1.0-beta.16](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.0-beta.16) — published 2026-10-27

Changes since `v1.1.0-beta.12` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.0-beta.12...v1.1.0-beta.16)).

### Changed

- Release shortcut keys reserved by removed commands. ([`6f324f68`](https://github.com/SebRoLENS/curvemole/commit/6f324f68eb6cf3f09637724c9164d9615410c2d9))
- Allocate preferred shortcuts before restoring saved assignments. ([`084f49ae`](https://github.com/SebRoLENS/curvemole/commit/084f49ae86b7918963a040c7607c8b722ca33438))
- Expand simple shortcuts for larger native menus. ([`b153f94c`](https://github.com/SebRoLENS/curvemole/commit/b153f94c6aff23adc9bdec0eeca49b058cb4081a))

### Fixed

- Fix point editing, reapply edited backgrounds and simplify keyboard shortcuts. ([`12ff4187`](https://github.com/SebRoLENS/curvemole/commit/12ff4187f3c1ddd0bfc42fca0f10957f03e7ac5a))

## [1.1.0-beta.12](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.0-beta.12) — published 2026-10-27

Changes since `v1.1.0-beta.11` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.1.0-beta.11...v1.1.0-beta.12)).

### Changed

- Infer point-based function options, reopen control points and add command shortcuts. ([`dbc8a656`](https://github.com/SebRoLENS/curvemole/commit/dbc8a656fb81ef122601ca153bc00528cec7b2b1))

## [1.1.0-beta.11](https://github.com/SebRoLENS/curvemole/releases/tag/v1.1.0-beta.11) — published 2026-10-27

Changes since `v1.0.2-beta.8` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.0.2-beta.8...v1.1.0-beta.11)).

### Changed

- Configure function options and initial parameter bounds before insertion. ([`f3d9c4ba`](https://github.com/SebRoLENS/curvemole/commit/f3d9c4ba69310416f1d7c5d67347ab3d58e7992a))
- Target 1.1.0 beta releases and fix manual validation. ([`8ca1d46d`](https://github.com/SebRoLENS/curvemole/commit/8ca1d46d359ae0c108be1bc256f7ba451e10992a))

### Documentation

- Link beta releases to verified Zenodo version DOIs. ([`ee7b342f`](https://github.com/SebRoLENS/curvemole/commit/ee7b342ff47d4113a5909f7a6646fbd030121a5a))

## [1.0.2-beta.8](https://github.com/SebRoLENS/curvemole/releases/tag/v1.0.2-beta.8) — published 2026-10-26

Changes since `v1.0.2-beta.6` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.0.2-beta.6...v1.0.2-beta.8)).

### Changed

- Improve Calculator and edit function initialization points. ([`56f33d11`](https://github.com/SebRoLENS/curvemole/commit/56f33d113f19bc82b9f45c6ea6c77ac3e38ccba3))
- Keep point-placement instructions above the editing controls. ([`88397a75`](https://github.com/SebRoLENS/curvemole/commit/88397a75b79a192006d09b19e5041e3685e96f29))

## [1.0.2-beta.6](https://github.com/SebRoLENS/curvemole/releases/tag/v1.0.2-beta.6) — published 2026-10-26

Changes since `v1.0.2-beta.4` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.0.2-beta.4...v1.0.2-beta.6)).

### Changed

- Open selected files in one desktop instance and import batch. ([`ea3c4cde`](https://github.com/SebRoLENS/curvemole/commit/ea3c4cdef967b67697388d4170992f7bd3d46595))
- Keep Windows file-open pipes alive until acknowledgement is read. ([`992ee78b`](https://github.com/SebRoLENS/curvemole/commit/992ee78b9095a95346b897b8c5e85eb3aa8080a4))

## [1.0.2-beta.4](https://github.com/SebRoLENS/curvemole/releases/tag/v1.0.2-beta.4) — published 2026-10-26

Changes since `v1.0.1` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.0.1...v1.0.2-beta.4)).

### Added

- Add reversible Stable and Beta update channels. ([`90f7c2b6`](https://github.com/SebRoLENS/curvemole/commit/90f7c2b6dc5c1bc43eedd3c981686dc95d1a8d1e))
- Add a manual testing-to-stable promotion workflow. ([`b3f5e052`](https://github.com/SebRoLENS/curvemole/commit/b3f5e052840a47666c7bd9b57b52345e5b1447dd))

### Changed

- Plan beta builds on the runner's bootstrap Python. ([`6d96a190`](https://github.com/SebRoLENS/curvemole/commit/6d96a1904acde95092cd0a2abe49eaa8c075cf68))
- Keep beta planning regression independent of future stable version bumps. ([`fe5ca4ae`](https://github.com/SebRoLENS/curvemole/commit/fe5ca4aea04ebaf70f73726d1ada145991aceac5))
- Reduce startup imports and load plugins after first paint. ([`82494ca1`](https://github.com/SebRoLENS/curvemole/commit/82494ca18acf22a2fac87b393940f1e25b69c333))

### Documentation

- Fix website publication after DOI metadata sync. ([`36ef3e21`](https://github.com/SebRoLENS/curvemole/commit/36ef3e217853e31fc2d20d97c4187d4e7632c7d3))
