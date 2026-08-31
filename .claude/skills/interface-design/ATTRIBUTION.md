# Where this came from

`SKILL.md`, the two commands in `.claude/commands/`, and `reference/` are
[interface-design](https://github.com/Dammyjay93/interface-design) by Damola
Akinleye, MIT licensed. The licence is alongside this file.

Copied in at the repository's `main` as of 31 August 2026, unmodified.

Deliberately **not** copied:

* `.githooks/pre-commit` — the author's own release automation. It rewrites
  version strings with `sed` on commit, which is their business and not
  something to run in this repository.
* `.claude-plugin/` — packaging metadata for distributing the plugin.
* `agents/openai.yaml` — configuration for a different host.

Nothing in what was copied reaches the network, runs a command, or reads
anything outside the repository. It is guidance, and it was read before being
installed.
