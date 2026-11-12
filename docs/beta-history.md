# Published beta history

Generated from beta tags and the GitHub release catalog (when available). Beta run numbers may have gaps. Each section describes changes between consecutive published betas, or since the previous stable release. The cumulative stable-cycle history is in `CHANGELOG.md`.

## [1.3.0-beta.132](https://github.com/SebRoLENS/curvemole/releases/tag/v1.3.0-beta.132) — published 2026-11-12

Changes since `v1.3.0-beta.130` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.3.0-beta.130...v1.3.0-beta.132)).

### Changed

- Open independent CurveMole projects and keep selected files in one import. ([`49561306`](https://github.com/SebRoLENS/curvemole/commit/49561306b7996f0b7ff942637c152cfa8a175331))

## [1.3.0-beta.130](https://github.com/SebRoLENS/curvemole/releases/tag/v1.3.0-beta.130) — published 2026-11-11

Changes since `v1.3.0-beta.127` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.3.0-beta.127...v1.3.0-beta.130)).

### Added

- Add formula and error-bar icons to the tool toolbar. ([`9d202ea3`](https://github.com/SebRoLENS/curvemole/commit/9d202ea3c0a88d4d5b7a525dabf2033902702865))

### Changed

- Give Undo and Redo stopwatch icons. ([`59e4a080`](https://github.com/SebRoLENS/curvemole/commit/59e4a0804a9bf4e950ef74033278e9286b1df66b))
- Use a plus badge for the Restore Background icon. ([`fffa586a`](https://github.com/SebRoLENS/curvemole/commit/fffa586a1f9c13197f5758eb9b53cf441ae1699e))
- Open or focus tool tabs from a right-aligned toolbar group. ([`c95abbf0`](https://github.com/SebRoLENS/curvemole/commit/c95abbf054229b8bdc513e6c198480c1d423f2ac))
- Open Model and parameters from the toolbar and highlight the active tool. ([`392dd5bd`](https://github.com/SebRoLENS/curvemole/commit/392dd5bdaf02b4b36822044e28f2b52e0c607d07))
- Verify toolbar alignment at a platform-appropriate width. ([`f3d75044`](https://github.com/SebRoLENS/curvemole/commit/f3d75044571c08f06791d33b36b6f926ae82447c))

## [1.3.0-beta.127](https://github.com/SebRoLENS/curvemole/releases/tag/v1.3.0-beta.127) — published 2026-11-11

Changes since `v1.3.0-beta.119` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.3.0-beta.119...v1.3.0-beta.127)).

### Changed

- Highlight dock tab arrows and preserve panel titles. ([`3da3a6b5`](https://github.com/SebRoLENS/curvemole/commit/3da3a6b5e85bfdec8d0fe78c51ebc433068c7d97))
- Verify dock tab scrolling across Qt platform styles. ([`7e5bf6b1`](https://github.com/SebRoLENS/curvemole/commit/7e5bf6b19d19bb71d76ae6a1268ee1fa9cf964b1))
- Keep dock tabs scrollable in narrow panels. ([`78744053`](https://github.com/SebRoLENS/curvemole/commit/787440532ef068dd4b4c73a27a4c641ab3934712))
- Verify full dock titles when captions elide. ([`d852fed0`](https://github.com/SebRoLENS/curvemole/commit/d852fed0b6ef54303cc45540ee92d672ccd2f110))
- Use the official Ubuntu archive for Linux CI dependencies. ([`9e3a540e`](https://github.com/SebRoLENS/curvemole/commit/9e3a540efbab6d49623f315f9eb28f27f7377ceb))
- Fall back to the Princeton Ubuntu mirror when Canonical is unreachable. ([`c8225622`](https://github.com/SebRoLENS/curvemole/commit/c822562259605b467c63fbdea2c5697195be0900))
- Publish the validated CurveMole 1.3.0 beta. ([`32edb3da`](https://github.com/SebRoLENS/curvemole/commit/32edb3da40daea3bbda7da685007c39d62c58673))

### Fixed

- Fix scientific fit, uncertainty, and spectrum data integrity. ([`6a86fca6`](https://github.com/SebRoLENS/curvemole/commit/6a86fca66a804234af9c37ccade369151f0c44d9))

## [1.3.0-beta.119](https://github.com/SebRoLENS/curvemole/releases/tag/v1.3.0-beta.119) — published 2026-11-11

Changes since `v1.3.0-beta.117` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.3.0-beta.117...v1.3.0-beta.119)).

### Changed

- Keep personal AppImage update handling out of public builds. ([`baa4033b`](https://github.com/SebRoLENS/curvemole/commit/baa4033b0e30c69fad66feee0c1ab6bb2c1d61d7))
- Keep mouse wheel zoom available in Mask mode. ([`3ff02ebb`](https://github.com/SebRoLENS/curvemole/commit/3ff02ebbdeaa67c2a4819d63b04617f3562e4ecd))

## [1.3.0-beta.117](https://github.com/SebRoLENS/curvemole/releases/tag/v1.3.0-beta.117) — published 2026-11-10

Changes since `v1.2.3-beta.103` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.2.3-beta.103...v1.3.0-beta.117)).

### Added

- Support matching columns by position in batch imports. ([`f80f7b6a`](https://github.com/SebRoLENS/curvemole/commit/f80f7b6adb3fd80488adc10252be91eb537ee930))

### Changed

- Drag series, spectra, and functions into a new order. ([`8f1d42b3`](https://github.com/SebRoLENS/curvemole/commit/8f1d42b315dc74609eff4810d24a8275be81b947))
- Identify local AppImages and preserve unpublished changes during updates. ([`e061faa4`](https://github.com/SebRoLENS/curvemole/commit/e061faa40f9a4d1abc8b4c50a1a8da5a70635112))
- Collapse dock panels and keep tab widths independent. ([`6deab0fe`](https://github.com/SebRoLENS/curvemole/commit/6deab0fe0593ac996a6d6eb11d23d437599f0953))
- Ask before reusing an import header choice and target CurveMole 1.3.0. ([`3d31e8e1`](https://github.com/SebRoLENS/curvemole/commit/3d31e8e1f03713a93045d06275786262fcda7c0a))
- Use a supported macOS runner for beta validation. ([`388f048d`](https://github.com/SebRoLENS/curvemole/commit/388f048d4a40e65891dc90a88b26962d8b6951cb))
- Autoscale the plot when clicking a data series. ([`b5a38ebe`](https://github.com/SebRoLENS/curvemole/commit/b5a38ebef2a38c1b98093a0f05e880cce9f206fb))
- Recognize Quick Start asset URLs on Windows. ([`32088cbb`](https://github.com/SebRoLENS/curvemole/commit/32088cbb2b16d8e20bb273850220de49e8c96bb4))

### Documentation

- docs: streamline README and highlight community plugins. ([`b00701d7`](https://github.com/SebRoLENS/curvemole/commit/b00701d7a9829443c92ee8447fae690bbfb634c1))
- docs: clarify homepage and highlight scientific workflows and plugins. ([`49509c39`](https://github.com/SebRoLENS/curvemole/commit/49509c391f3534ed8a9531c7813e76818ce3555f))
- docs: explain token-saving AI automation audits in README and homepage. ([`c65ba295`](https://github.com/SebRoLENS/curvemole/commit/c65ba295a698a27f39160853b4305f7559da6b91))
- docs: add illustrated Raman quick start with dark stable GUI captures. ([`b6c4af74`](https://github.com/SebRoLENS/curvemole/commit/b6c4af74db4452410c1539f1a0388eba1f9c2da2))

## [1.2.3-beta.103](https://github.com/SebRoLENS/curvemole/releases/tag/v1.2.3-beta.103) — published 2026-11-05

Changes since `v1.2.0-beta.88` ([compare](https://github.com/SebRoLENS/curvemole/compare/v1.2.0-beta.88...v1.2.3-beta.103)).

### Added

- Support all Git installation layouts in Windows workflow tests. ([`99779f9a`](https://github.com/SebRoLENS/curvemole/commit/99779f9ab3a9fc0dfc576a3af58fd50ab54cfec8))

### Changed

- Run stable release jobs after optional promotion is skipped [release 1.2.0]. ([`e3d23ed8`](https://github.com/SebRoLENS/curvemole/commit/e3d23ed88175ae573e245f470e4f0c458183f5b6))
- Activate validated release and CI workflows. ([`6e54afec`](https://github.com/SebRoLENS/curvemole/commit/6e54afeccdde93e828f89b6bc68c2c59f915d3ab))
- Allow runner variation in Windows GUI validation. ([`e2b79fbc`](https://github.com/SebRoLENS/curvemole/commit/e2b79fbc63b73c1f550ccd48e235cb0f789af074))
- Activate Windows CI timeout headroom. ([`02b1a7a9`](https://github.com/SebRoLENS/curvemole/commit/02b1a7a90286de10edf84101ed46be2350e4db24))
- End completed Windows CI test workers reliably. ([`ec2e13df`](https://github.com/SebRoLENS/curvemole/commit/ec2e13df323a906eebaf851a3d1f5ee9f90a6027))
- Activate reliable Windows CI worker shutdown. ([`5510b896`](https://github.com/SebRoLENS/curvemole/commit/5510b896d00210f4fa6bfef4f2630880a53ae232))
- Compare current and Fusion desktop styles across platforms. ([`a07c2279`](https://github.com/SebRoLENS/curvemole/commit/a07c2279a5f709f005e3adef3710cc9c10325195))
- Install native X11 dependencies for desktop style screenshots. ([`a1c166f7`](https://github.com/SebRoLENS/curvemole/commit/a1c166f7d29611dc6b1ece9341810dc719bebcaf))

### Fixed

- Fix beta withdrawal verification through immutable release ID. ([`591d0543`](https://github.com/SebRoLENS/curvemole/commit/591d054398893b058181e5c7149de02621bad594))
- Fix opening valid projects beyond automatic size thresholds. ([`bb3c2842`](https://github.com/SebRoLENS/curvemole/commit/bb3c2842db97799c3f23375760be7d83361ee3dc))
- Fix workflow coordination and consistent release packaging. ([`490e57b5`](https://github.com/SebRoLENS/curvemole/commit/490e57b5128f91d3998a1fd6a27ada8f1f66197d))
- Fix Git Bash selection in Windows workflow tests. ([`3381db2f`](https://github.com/SebRoLENS/curvemole/commit/3381db2f48a915bddea69d51d594bbb5967ebd8e))
- Fix inconsistent desktop themes with Fusion controls by default. ([`c82291dc`](https://github.com/SebRoLENS/curvemole/commit/c82291dcf9b7e476fb7124db2e34bd5e2be9146c))
- Unify Calculator operations under Custom formulas, including expressions across table columns. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))
- Make Calculator formulas reusable with adjacent Load formula and Save formula controls. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))
- Show each result column once as c1, c2 and so on, with current X/Y assignments, and make column insertion searchable. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))
- Group default formula, function and plugin folders under curvemole_data. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))
- Make the Background control visible for the selected model functions, including mixed selections. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))
- Display effectively zero positive parameter bounds as 0 while preserving safe numerical limits. ([`32c94e66`](https://github.com/SebRoLENS/curvemole/commit/32c94e66e0f4b8a2e0e7a5af31bbae0bf6265eac))

### Documentation

- docs: publish CurveMole RRID in public citation, manuals and website. ([`9a34f697`](https://github.com/SebRoLENS/curvemole/commit/9a34f697071f26e1dff93a2a258c1d002a87be7e))
- docs: publish all-versions Concept DOI beside release citations. ([`df8bdbbb`](https://github.com/SebRoLENS/curvemole/commit/df8bdbbba4a678268ee01c7cad3372e547859599))
- Publish consistent citation guidance for the current stable release. ([`180ad6ea`](https://github.com/SebRoLENS/curvemole/commit/180ad6ea291086624ea698123be6e7e71adde1a7))
- Publish citation validation correction from testing. ([`6f36f22e`](https://github.com/SebRoLENS/curvemole/commit/6f36f22e1e533ac402335ab74a54e30420c6aa2d))
- Publish consent-gated Google Analytics for CurveMole website. ([`fce83d59`](https://github.com/SebRoLENS/curvemole/commit/fce83d59893de022576c11147294731715f4dfae))
- Publish reviewed website pages and sitemap from testing. ([`c81c5661`](https://github.com/SebRoLENS/curvemole/commit/c81c5661f196888b7060b59eac40a3cd676cce03))
- Publish tested website lint corrections from testing. ([`8f4ab605`](https://github.com/SebRoLENS/curvemole/commit/8f4ab605aa994d6aff53c958c7893fdf7e6007cd))
- Switch CurveMole website to cookie-free Cloudflare analytics. ([`f526eeca`](https://github.com/SebRoLENS/curvemole/commit/f526eeca201ff9fa8f7981fbdf73a933b37faca0))
- Fix stable release staging of website citations. ([`ad1f16f2`](https://github.com/SebRoLENS/curvemole/commit/ad1f16f262b3ef91ee1a42b3cf9d9da7742ef8f8))
- Fix website publication after stable documentation preparation. ([`60af148e`](https://github.com/SebRoLENS/curvemole/commit/60af148e6ba46e596b5b9b1e660d0ee076e59ddd))
- Recognize named stable promotions in website publication. ([`9bc14fc9`](https://github.com/SebRoLENS/curvemole/commit/9bc14fc968c61457dac8a2163bd3e13ab2c3a0f8))
- Activate stable promotion website event guard. ([`db691767`](https://github.com/SebRoLENS/curvemole/commit/db691767b4bd4d3ad218496b16ca4a1de218a079))

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
