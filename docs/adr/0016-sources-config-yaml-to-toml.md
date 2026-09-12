# Sources configuration migrated from YAML to TOML

The planner's search/source configuration was serialized as YAML (`config/sources.yaml`), pulled in via the `pyyaml` runtime dependency. We switched to TOML (`config/sources.toml`) parsed with the standard-library `tomllib` module, dropping `pyyaml` entirely. The project already requires Python `>=3.12`, and `tomllib` ships in the stdlib since 3.11, so TOML parsing needs no third-party dependency — aligning with the minimal-dependency philosophy and structural parity with the private sibling project (developer-core ADR-0017). Test fixtures that need to *write* TOML use the dev-only `tomli-w` package, since `tomllib` is read-only.

## Considered Options

- **Keep YAML + `pyyaml`.** Widespread and comment-friendly, but carries a runtime dependency purely for reading a small config file. Rejected: the dependency exists only to parse one file, and `pyyaml` has a non-trivial CVE history (e.g. CVE-2020-14343) that `pip-audit` flags.
- **TOML + stdlib `tomllib` (chosen).** Zero runtime dependency, type-rigid (no implicit `null`/tag surprises), native to the Python ecosystem (`pyproject.toml` itself is TOML). Trade-off: `tomllib` is read-only, so tests need `tomli-w` to generate fixtures.
- **JSON.** Stdlib `json`, no dependency, but no comments — unacceptable for a user-facing config file that documents intent inline.

## Consequences

- `pyyaml` and `types-pyyaml` are removed; `tomli-w` is added as a dev-only dependency.
- `AppConfig` loads the config in binary mode (`open(path, "rb")`) as `tomllib.load` requires a binary file object.
- The `SourcesConfig` / `SearchParametersConfig` Pydantic schemas are unchanged — only the serialization format and loader changed.

## Inspiration & References

- Python `tomllib` standard library (3.11+), read-only parser requiring a binary file object: https://docs.python.org/3/library/tomllib.html
- `tomli-w` — minimal TOML writer used for test fixtures: https://pypi.org/project/tomli-w/
- Reference implementation: private sibling project (developer-core ADR-0017): `config/sources.toml`, `config/sources.example.toml`, `orchestrator/sources_config.py`.
- The choice mirrors the broader Python packaging ecosystem, where `pyproject.toml` (PEP 518/621) established TOML as the canonical config format for Python projects, reinforcing the "no extra dependency" advantage.
