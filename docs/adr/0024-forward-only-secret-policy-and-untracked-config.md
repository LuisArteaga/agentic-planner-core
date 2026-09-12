# Forward-only secret policy and untracked personal configuration

The repository is prepared for public release under its existing MIT license (issue #76). Two kinds of state must never become public: the personal LLM routing setup (`config/factory.json`, `config/sources.toml`) and any credential that ever reached git history. We adopt a forward-only secret policy: history is NOT rewritten; instead the full history received a one-time gitleaks scan (the default `--all` pass plus a merge-diff supplemental pass — both clean) and GitHub push protection is enabled, so future secrets are blocked at push time. The real config files are untracked (gitignored like `.env`) while the tracked `config/*.example.*` files document their shape; `sources.example.toml` doubles as the fresh-clone runtime fallback.

## Considered Options

- **Rewrite git history to purge secrets/config.** Rejected (grilling decision on #76): rewriting SHAs breaks every existing clone, requires a force-push, and destroys the append-only review trail; with a clean scan there is nothing to purge anyway.
- **Keep the config files tracked.** Rejected: they encode a personal spend/routing profile (which models and providers this deployment pays for); publishing them would expose usage patterns and invite accidental edits of private state through public PRs.
- **Forward-only (chosen).** Non-destructive, auditable, and enforced going forward by the gitleaks CI gate (`secret-scan.yml`) plus push protection; the one-time full-history scan provides the release assurance.

## Consequences

- `config/factory.json` and `config/sources.toml` are gitignored; existing local copies keep working. Fresh clones fall back to `config/sources.example.toml` (validated identically, with a warning) and to the built-in model defaults in `resolve_model_config` — `AppConfig` no longer hard-requires the real files. Explicitly passed config paths still fail fast when missing.
- `config/factory.example.json` intentionally keeps placeholder model ids (`provider/model-name`) and is documentation-only: it is never resolved at runtime, because placeholder models would override the known-good built-in defaults.
- CI runs on a fresh checkout without the factory config: the toolkit's `judge_config.load_factory_config` returns `{}` on a missing file and falls back to hardcoded models (toolkit v1.7.0), and the planner's `resolve_model_config` catches the missing file and uses its built-in defaults.
- The dead `push.paths: config/factory.json` trigger was removed from `eval.yml`; the workflow remains available via `workflow_dispatch` and `workflow_call`.
- A real credential discovered later must be rotated regardless of this policy — forward-only means "no rewrite", never "ignore findings".

## Inspiration & References

- Grilling decision record for issue #76 (forward-only policy; history rewrite rejected).
- Gitleaks v8.30 CLI (`gitleaks git --log-opts="--all"`), including the merge-diff supplemental pass (`--diff-merges=first-parent`): https://github.com/gitleaks/gitleaks
- GitHub push protection: https://docs.github.com/code-security/secret-scanning/push-protection-for-repositories-and-organizations
- Precedent for optional config loading: quality-gates-toolkit v1.7.0 `judge_config.load_factory_config` ("returns an empty dict on missing or malformed files, never raises").
