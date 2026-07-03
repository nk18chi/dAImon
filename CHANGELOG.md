# Changelog

## 0.1.0 (2026-07-03)


### Features

* **backend:** add codex backend (one-shot `codex exec`) ([#41](https://github.com/effekt/dAImon/issues/41)) ([43ac206](https://github.com/effekt/dAImon/commit/43ac206b8eae1e3e7b41a3c4fce6a3e4b1a1174e))
* **daemons:** add datadog-log-reviewer daemon + datadog source profile ([#47](https://github.com/effekt/dAImon/issues/47)) ([b5de106](https://github.com/effekt/dAImon/commit/b5de106eefd6415f6d3a1afff160bbc7cc5f044e))
* **daemons:** add risk-tiered dependency-reviewer daemon ([#46](https://github.com/effekt/dAImon/issues/46)) ([2cb3235](https://github.com/effekt/dAImon/commit/2cb32351b926e661c3ecb4a12c7e8e343eb28d10))
* **daemons:** audit sources + add reply-to-story-comments ([b6e3871](https://github.com/effekt/dAImon/commit/b6e387132f6bc613048d8413dcb67ba17e98dc32))
* **daemons:** enable Codex second opinion on review-prs and story-reviewer ([#42](https://github.com/effekt/dAImon/issues/42)) ([871befe](https://github.com/effekt/dAImon/commit/871befeb183924250dddbcf4db34f18bdaf33448))
* **daemons:** richer, configurable review/reply output ([#16](https://github.com/effekt/dAImon/issues/16)) ([d8e8c82](https://github.com/effekt/dAImon/commit/d8e8c82094ee46097f07c668d2ecd59a9392546e))
* dAImon — scheduled autonomous agent daemon pipeline ([daf5230](https://github.com/effekt/dAImon/commit/daf52301be6f2268beaf4a087ecf5b0b9ac658ac))
* daimon init, first-run DX, and OSS scaffolding ([#17](https://github.com/effekt/dAImon/issues/17)) ([704a69e](https://github.com/effekt/dAImon/commit/704a69e6a7a1b1165ec7879ab5caf036845a8544))
* **doctor:** check codex CLI/auth and warn on untrusted working_dir ([#43](https://github.com/effekt/dAImon/issues/43)) ([5a3ae44](https://github.com/effekt/dAImon/commit/5a3ae440578a0a6ffdc9010d5f1160c17a01d787))
* github source profile — shared gate helpers + bats ([#14](https://github.com/effekt/dAImon/issues/14)) ([b8a7368](https://github.com/effekt/dAImon/commit/b8a736848e0010b3fbf151cfc5651f8d9a6a13ab))
* JSON Schema for daemon.toml (editor validation) ([#11](https://github.com/effekt/dAImon/issues/11)) ([eca9f83](https://github.com/effekt/dAImon/commit/eca9f8389cf4ecee560e2b087992bf2393f08f8c))
* let daimon init select which daemons to run ([#18](https://github.com/effekt/dAImon/issues/18)) ([c0a6914](https://github.com/effekt/dAImon/commit/c0a691452f151a48fcc5cffeab3e4956697538aa))
* **mcp:** opt-in Codex MCP for daemon sessions ([#40](https://github.com/effekt/dAImon/issues/40)) ([2875932](https://github.com/effekt/dAImon/commit/2875932e1e93176ee2f6262573f5f3e0a8708b7b))
* multi-source profiles + story-aware PR review ([#13](https://github.com/effekt/dAImon/issues/13)) ([93447b8](https://github.com/effekt/dAImon/commit/93447b85abf10f65d15c5106677bdaae892e740c))
* pr-manager daemon — shepherd open PRs to merge ([#3](https://github.com/effekt/dAImon/issues/3)) ([6a49021](https://github.com/effekt/dAImon/commit/6a49021f98b71f8c056afd717c6c53b5582b0718))
* **pr-manager:** draft self-promotion + configurable reviewers ([#4](https://github.com/effekt/dAImon/issues/4)) ([c7f69ed](https://github.com/effekt/dAImon/commit/c7f69edb5ee38ee63144cd8731c96b19d2934357))
* **pr-manager:** optional unattended auto-merge ([#5](https://github.com/effekt/dAImon/issues/5)) ([dc336fe](https://github.com/effekt/dAImon/commit/dc336fefa03a767084d4afbb4fde6296669ad889))
* read-only vs read-write source modes (reference split) ([#15](https://github.com/effekt/dAImon/issues/15)) ([f4e50c7](https://github.com/effekt/dAImon/commit/f4e50c7eda7be82d398f33ad8a97c441ba0ead55))
* **review:** risk-gated review decisions + reply-driven re-review ([#7](https://github.com/effekt/dAImon/issues/7)) ([bbae133](https://github.com/effekt/dAImon/commit/bbae133f976bd8976dd31ec4f9a31664f97fe802))
* **shortcut:** support epic_id on story creation ([#50](https://github.com/effekt/dAImon/issues/50)) ([17017d0](https://github.com/effekt/dAImon/commit/17017d032f4ef7723a09e143a8a3a04f25b35e12))
* **skills:** shared conventions include for comment-posting daemons ([#12](https://github.com/effekt/dAImon/issues/12)) ([fdc7eca](https://github.com/effekt/dAImon/commit/fdc7eca51d3bdd8c00b720bb091b66ff38493819))
* **tui:** audit — newest-first log tail, complete manage menu, drop dead source field ([#20](https://github.com/effekt/dAImon/issues/20)) ([46caf24](https://github.com/effekt/dAImon/commit/46caf24ed859e0c46c69e68b3e47b8791cb70e84))
* **tui:** batch refresh queries; safer daemon duplication ([#21](https://github.com/effekt/dAImon/issues/21)) ([4418dc6](https://github.com/effekt/dAImon/commit/4418dc697a0c8b34c7951d10a70768e70d130ddc))
* **tui:** glyph-based status with a legend (no colour-only state) ([#22](https://github.com/effekt/dAImon/issues/22)) ([4972c56](https://github.com/effekt/dAImon/commit/4972c56e96eeee25c7b4d1d20c4ce3610be3c6c8))
* **tui:** separate daemon inputs from profile fields in config editor ([#19](https://github.com/effekt/dAImon/issues/19)) ([7a24390](https://github.com/effekt/dAImon/commit/7a243907e22ef277ac0b383051a31ac39f114a46))


### Bug Fixes

* full verbosity in reply daemons names files/changes ([#28](https://github.com/effekt/dAImon/issues/28)) ([0d60b05](https://github.com/effekt/dAImon/commit/0d60b05deca6e0c8656c24e95c6244aadd706b1c))
* **review-prs:** make discovery gate state-aware ([#6](https://github.com/effekt/dAImon/issues/6)) ([a15d658](https://github.com/effekt/dAImon/commit/a15d658c1cd9ef9adedcdb783d47db65d7ea2135))
* **runtime:** enforce hourly budget gate and make watchdog backend-agnostic ([#44](https://github.com/effekt/dAImon/issues/44)) ([ad6736b](https://github.com/effekt/dAImon/commit/ad6736be7037a289a2df3080ed7dbcda9c9cb593))
* scope work-queue to the owner's own stories ([ac9deda](https://github.com/effekt/dAImon/commit/ac9dedac2ab7fa739a7447995913ad9f2624f12d))


### Performance Improvements

* memoize discover() + single-shot daemon-env (kill per-run process storm) ([#10](https://github.com/effekt/dAImon/issues/10)) ([e1571d1](https://github.com/effekt/dAImon/commit/e1571d119254fee3c2920f87dd49afdf017cc916))


### Documentation

* add a TUI screenshot to the README ([#26](https://github.com/effekt/dAImon/issues/26)) ([fb98db8](https://github.com/effekt/dAImon/commit/fb98db86e0ab645bb190f36d03955c6ca675bd45))
* add AGENTS.md + committed permissions-only .claude/settings.json ([#9](https://github.com/effekt/dAImon/issues/9)) ([509504d](https://github.com/effekt/dAImon/commit/509504d02dcb1532179259087dc2738874d4630c))
* add writing-a-source how-to for source profiles ([#49](https://github.com/effekt/dAImon/issues/49)) ([2803a8a](https://github.com/effekt/dAImon/commit/2803a8ab9b98fa6c3fab115dc07ad338c72ffa73))
* correct main protection description (no required reviews) ([#36](https://github.com/effekt/dAImon/issues/36)) ([8cd5f56](https://github.com/effekt/dAImon/commit/8cd5f560d1b4ffca599e4648a591d4c573f47c8c))
* fix branch-protection command and document release-PR merges ([#35](https://github.com/effekt/dAImon/issues/35)) ([57974d6](https://github.com/effekt/dAImon/commit/57974d6982baaaf03996bd36d85e671373861cef))
* generate per-daemon READMEs + index, enforced ([#27](https://github.com/effekt/dAImon/issues/27)) ([e9d63fd](https://github.com/effekt/dAImon/commit/e9d63fd3c1a91b5f35b00c4c097b351bc36225cb))
* lead README with purpose; fill CONTRIBUTING gaps ([#29](https://github.com/effekt/dAImon/issues/29)) ([e85b23b](https://github.com/effekt/dAImon/commit/e85b23bf15d25e56e6bf89a2d0eb1d7ef4f0c477))

## Changelog

All notable changes are recorded here. Entries below are generated from
[Conventional Commits](https://www.conventionalcommits.org/) by
[release-please](https://github.com/googleapis/release-please); the version follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).
