import os
import pathlib
import json
import functools
import logging
from typing import List, Optional, Dict, Any, TYPE_CHECKING
import tomllib
from pydantic import BaseModel, Field, model_validator
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
import httpx
from langchain_openai import ChatOpenAI

if TYPE_CHECKING:
    from planner.zero_tolerance.models import ZeroToleranceConfig

logger = logging.getLogger("planner.config")

# Per-call LLM transport timeout defaults (ADR-0021). The ``read`` phase equals
# ``timeout_seconds`` — for a *non-streaming* call no bytes arrive until the
# provider finishes computing, so ``read`` bounds the maximum legitimate
# generation time (e.g. ``thinking: max``). ``connect``/``write``/``pool`` are
# tight so a dead/unreachable endpoint fails fast instead of consuming the full
# ``read`` budget.
DEFAULT_LLM_TIMEOUT_SECONDS = 600.0
DEFAULT_LLM_CONNECT_TIMEOUT = 10.0
DEFAULT_LLM_WRITE_TIMEOUT = 30.0
DEFAULT_LLM_POOL_TIMEOUT = 30.0
# No silent SDK retries: a never-responding endpoint must break after *one*
# timeout window, not ``(max_retries + 1) * timeout``. Retry isolation lives at
# the application layer (per-query / per-draft, ADR-0005).
DEFAULT_LLM_MAX_RETRIES = 0

# Config file locations (ADR-0024). The real routing setup is untracked
# (gitignored like ``.env``); the tracked example files document the shape and
# serve as the fresh-clone fallback for sources. The example factory documents
# the shape only — its placeholder model ids are never resolved at runtime.
DEFAULT_SOURCES_PATH = "config/sources.toml"
EXAMPLE_SOURCES_PATH = "config/sources.example.toml"
DEFAULT_FACTORY_PATH = "config/factory.json"


def load_env_file(filepath: str = ".env") -> None:
    """Loads environment variables from a .env file (standard library only)."""
    path = pathlib.Path(filepath)
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # Remove quotes if present
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                # Set key in environment if not already set (precedence to process env)
                if key not in os.environ:
                    os.environ[key] = val


class SearchParametersConfig(BaseModel):
    """Pydantic schema for search parameters configuration."""

    engine: str = "auto"
    search_context_size: Optional[str] = None
    max_results: Optional[int] = None
    max_total_results: Optional[int] = None
    excluded_domains: List[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    """Zero-Trust prompt-injection defense configuration (ADR-0020).

    Defense ranking (per the issue pre-selection verdict): the existing
    ``strict`` source allowlist (structural control) plus the LLM Security
    Judge plus the HITL publish gate are the PRIMARY defenses; the regex
    pre-filter (``sanitize_inputs``) is a best-effort, fast, deterministic
    aid only — blacklisting on regex alone is brittle (OWASP A03:2021).
    """

    sanitize_inputs: bool = True
    audit_level: str = "normal"  # "off" | "normal" | "strict"
    require_approval: bool = True
    max_security_retries: int = 2

    @model_validator(mode="after")
    def _validate_audit_level(self) -> "SecurityConfig":
        allowed = {"off", "normal", "strict"}
        if self.audit_level not in allowed:
            raise ValueError(
                f"security.audit_level must be one of {sorted(allowed)}, "
                f"got '{self.audit_level}'."
            )
        return self


class SourcesConfig(BaseModel):
    """Pydantic schema for parsing and validating sources.toml configuration."""

    strict: bool = True
    urls: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    search: SearchParametersConfig = Field(default_factory=SearchParametersConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    zero_tolerance: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_strict_sources(self) -> "SourcesConfig":
        if self.strict and not self.urls and not self.domains:
            raise ValueError(
                "Strict-mode is enabled (strict: true), but both 'urls' "
                "and 'domains' are empty. At least one source must be defined."
            )

        # Normalize excluded_domains and check for overlaps
        if self.search and self.search.excluded_domains:
            normalized = [
                d.strip().lower()
                for d in self.search.excluded_domains
                if d and d.strip()
            ]
            self.search.excluded_domains = normalized

            whitelisted_domains = {d.strip().lower() for d in self.domains if d}
            whitelist_set = whitelisted_domains

            for ext in self.search.excluded_domains:
                if ext in whitelist_set:
                    logger.warning(
                        f"Overlap detected: Domain '{ext}' is defined in both allowed sources and excluded_domains."
                    )
        return self


class AppConfig:
    """System configuration class containing environment variables and toml settings."""

    def __init__(
        self,
        sources_toml_path: str = DEFAULT_SOURCES_PATH,
        factory_json_path: str = DEFAULT_FACTORY_PATH,
    ):
        # Load environment variables from .env if present
        load_env_file()

        # Validate system environment variables
        self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
        self.gh_pat = os.environ.get("GH_PAT") or os.environ.get("GH_TOKEN")
        self.github_repository = os.environ.get("GITHUB_REPOSITORY")
        # Resolve GITHUB_WORKSPACE
        workspace_env = os.environ.get("GITHUB_WORKSPACE")
        if workspace_env:
            workspace_path = pathlib.Path(workspace_env)
            if workspace_path.is_absolute():
                self.github_workspace = str(workspace_path.resolve())
            else:
                project_root = pathlib.Path(__file__).resolve().parents[1]
                workspaces_root = (project_root / ".workspaces").resolve()
                resolved_path = (workspaces_root / workspace_path).resolve()
                try:
                    resolved_path.relative_to(workspaces_root)
                except ValueError:
                    raise ValueError(
                        f"Path traversal detected: relative GITHUB_WORKSPACE path "
                        f"'{workspace_env}' resolves outside the '.workspaces' directory."
                    )
                self.github_workspace = str(resolved_path)
        else:
            self.github_workspace = os.getcwd()

        # Keep environment variable in sync for downstream modules/subprocesses
        os.environ["GITHUB_WORKSPACE"] = self.github_workspace

        missing = []
        if not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        if not self.gh_pat:
            missing.append("GH_PAT/GH_TOKEN")
        if not self.github_repository:
            missing.append("GITHUB_REPOSITORY")

        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}"
            )

        # Parse and validate sources.toml (ADR-0024). The personal routing
        # setup is untracked: when the default path is absent, fall back to
        # the tracked example configuration so fresh clones start cleanly.
        # Explicitly passed paths keep strict semantics (missing -> error).
        toml_path = pathlib.Path(sources_toml_path)
        if not toml_path.exists() and sources_toml_path == DEFAULT_SOURCES_PATH:
            example_path = pathlib.Path(EXAMPLE_SOURCES_PATH)
            if example_path.exists():
                logger.warning(
                    "Sources configuration not found at '%s'; falling back to "
                    "the tracked example configuration '%s'.",
                    sources_toml_path,
                    example_path,
                )
                toml_path = example_path

        if not toml_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {sources_toml_path}"
            )

        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            raise ValueError(f"Invalid TOML format in {toml_path}: {e}")

        # Validate parsed data via Pydantic
        try:
            self.sources = SourcesConfig.model_validate(data)
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}")

        # Parse and validate factory.json (ADR-0024). The personal routing
        # setup is untracked: when the default path is absent, startup skips
        # factory validation and model resolution falls back to the built-in
        # defaults (``resolve_model_config``). Present files — and explicitly
        # passed paths — still fail fast on missing or malformed content.
        factory_path = pathlib.Path(factory_json_path)
        if not factory_path.exists() and factory_json_path == DEFAULT_FACTORY_PATH:
            project_root = pathlib.Path(__file__).resolve().parents[1]
            factory_path = project_root / factory_json_path
        if factory_path.exists() or factory_json_path != DEFAULT_FACTORY_PATH:
            _load_factory_config(factory_json_path)
        else:
            logger.info(
                "Factory configuration not found (%s); using built-in model defaults.",
                factory_json_path,
            )

    def get_github_session(self) -> requests.Session:
        """Returns a requests.Session configured with a robust retry strategy and auth headers."""
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {self.gh_pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[403, 429, 500, 502, 503, 504],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))

        # Inject default timeout of 60 seconds for all session requests
        orig_request = session.request

        def request_with_timeout(*args, **kwargs):
            if "timeout" not in kwargs:
                kwargs["timeout"] = 60.0
            return orig_request(*args, **kwargs)

        session.request = request_with_timeout

        return session

    def get_zero_tolerance_config(
        self, cli_enabled: bool = False
    ) -> "ZeroToleranceConfig":
        """Build the Zero-Error-Tolerance AddOn config from sources.toml + CLI flag.

        The ``[zero_tolerance]`` table (optional) supplies thresholds; the CLI
        ``--zero-tolerance`` flag force-enables the AddOn.
        """
        from planner.zero_tolerance.models import ZeroToleranceConfig

        raw = self.sources.zero_tolerance or {}
        data = dict(raw)
        data["enabled"] = bool(data.get("enabled", False)) or cli_enabled
        return ZeroToleranceConfig.model_validate(data)


class ModelConfig(BaseModel):
    """Configuration for a specific LLM model used by a phase, node, or judge."""

    model: str
    routing: Optional[List[str]] = None
    temperature: Optional[float] = None
    options: Optional[Dict[str, Any]] = None
    max_tokens: Optional[int] = None
    # Per-call transport timeout (seconds) applied as the httpx ``read`` phase —
    # the maximum generation time for a non-streaming call before the call is
    # aborted. Bounded phases below are derived from it (ADR-0021). ``None`` →
    # ``DEFAULT_LLM_TIMEOUT_SECONDS``.
    timeout_seconds: Optional[float] = None
    # SDK-level retry count. Defaults to ``0`` (no silent stacking) — retry
    # isolation is handled at the application layer (per-query try/except in
    # ``web_search``, per-draft try/except in the master loop, ADR-0005). A
    # non-zero value multiplies the effective worst-case per-call budget
    # (``(max_retries + 1) * timeout``); see ADR-0021.
    max_retries: Optional[int] = None


class FactoryConfig(BaseModel):
    """Central model configuration schema loaded from config/factory.json."""

    factory_version: str
    cli_orchestration: Dict[str, ModelConfig]
    refine_graph_nodes: Dict[str, ModelConfig]
    ci_cd_pr_judges: Dict[str, ModelConfig]


@functools.lru_cache(maxsize=1)
def _load_factory_config(
    filepath: str = DEFAULT_FACTORY_PATH,
) -> FactoryConfig:
    """Loads and validates config/factory.json with caching."""
    path = pathlib.Path(filepath)
    if not path.exists():
        # Try finding relative to project root
        project_root = pathlib.Path(__file__).resolve().parents[1]
        path = project_root / filepath
        if not path.exists():
            raise FileNotFoundError(f"Factory configuration file not found: {filepath}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ValueError(f"Invalid JSON format in {filepath}: {e}")

    try:
        return FactoryConfig.model_validate(data)
    except Exception as e:
        raise ValueError(f"Factory configuration validation failed: {e}")


def resolve_model_config(phase_or_node: str) -> dict:
    """Resolves the LLM configuration (model, routing, temperature, options) for a phase or node."""
    load_env_file()

    # 1. Check environment overrides first
    env_vars = {
        "grill": ["GRILL_MODEL", "AGENT_MODEL"],
        "verify": ["VERIFY_MODEL", "AGENT_MODEL"],
        "draft": ["DRAFT_MODEL", "AGENT_MODEL"],
        "analyze_sources": [
            "REFINE_ANALYZE_SOURCES_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "web_search": ["REFINE_WEB_SEARCH_MODEL", "REFINE_MODEL", "AGENT_MODEL"],
        "propose_options": [
            "REFINE_PROPOSE_OPTIONS_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "evaluate_grade": [
            "REFINE_EVALUATE_GRADE_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "apply_decision": [
            "REFINE_APPLY_DECISION_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "publish_issue": ["REFINE_PUBLISH_ISSUE_MODEL", "REFINE_MODEL", "AGENT_MODEL"],
        "security_audit": [
            "REFINE_SECURITY_AUDIT_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "intent_gate": [
            "REFINE_INTENT_GATE_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "planning_judge": [
            "REFINE_PLANNING_JUDGE_MODEL",
            "REFINE_MODEL",
            "AGENT_MODEL",
        ],
        "syntax_lint": ["PR_SYNTAX_LINT_MODEL", "AGENT_MODEL"],
        "test_coverage": ["PR_TEST_COVERAGE_MODEL", "AGENT_MODEL"],
        "architecture": ["PR_ARCHITECTURE_MODEL", "AGENT_MODEL"],
        "security": ["PR_SECURITY_MODEL", "AGENT_MODEL"],
    }

    overridden_model = None
    if phase_or_node in env_vars:
        for var in env_vars[phase_or_node]:
            val = os.getenv(var)
            if val:
                overridden_model = val
                break

    # 2. Get factory settings if available
    factory_cfg = None
    try:
        factory = _load_factory_config()
        if factory:
            if phase_or_node in ["grill", "verify", "draft"]:
                factory_cfg = factory.cli_orchestration.get(phase_or_node)
            elif phase_or_node in [
                "analyze_sources",
                "web_search",
                "propose_options",
                "evaluate_grade",
                "apply_decision",
                "publish_issue",
                "security_audit",
                "intent_gate",
                "planning_judge",
            ]:
                factory_cfg = factory.refine_graph_nodes.get(phase_or_node)
            elif phase_or_node in [
                "syntax_lint",
                "test_coverage",
                "architecture",
                "security",
            ]:
                factory_cfg = factory.ci_cd_pr_judges.get(phase_or_node)
    except Exception:
        pass

    # 3. Define fallback defaults (normalized to kimi-2.7-code etc.)
    default_models = {
        "grill": "z-ai/glm-5.2",
        "verify": "z-ai/glm-5.2",
        "draft": "deepseek/deepseek-v4-pro",
        "analyze_sources": "deepseek/deepseek-v4-flash",
        "web_search": "deepseek/deepseek-v4-flash",
        "propose_options": "deepseek/deepseek-v4-pro",
        "evaluate_grade": "z-ai/glm-5.2",
        "apply_decision": "moonshotai/kimi-k2.7-code",
        "publish_issue": "moonshotai/kimi-k2.7-code",
        "security_audit": "z-ai/glm-5.2",
        "intent_gate": "z-ai/glm-5.2",
        "planning_judge": "z-ai/glm-5.2",
        "syntax_lint": "moonshotai/kimi-k2.7-code",
        "test_coverage": "moonshotai/kimi-k2.7-code",
        "architecture": "z-ai/glm-5.2",
        "security": "deepseek/deepseek-v4-pro",
    }

    # Provider routing fallbacks — mirror of config/factory.json.
    # Ensures CI always uses known-good providers even without factory.json,
    # preventing OpenRouter from routing to providers with active guardrails
    # that return empty responses (e.g. kimi-k2.7-code via non-DeepInfra providers).
    default_routing = {
        "grill": ["Together", "DeepInfra", "Fireworks", "Parasail", "Inceptron"],
        "verify": ["Together", "DeepInfra", "Fireworks", "Parasail", "Inceptron"],
        "draft": ["DeepInfra", "SiliconFlow", "Novita", "Parasail", "DeepSeek"],
        "analyze_sources": [
            "DeepInfra",
            "SiliconFlow",
            "Novita",
            "Parasail",
            "DeepSeek",
        ],
        "web_search": ["DeepInfra", "SiliconFlow", "Novita", "Parasail", "DeepSeek"],
        "propose_options": [
            "DeepInfra",
            "SiliconFlow",
            "Novita",
            "Parasail",
            "DeepSeek",
        ],
        "evaluate_grade": [
            "Together",
            "DeepInfra",
            "Fireworks",
            "Parasail",
            "Inceptron",
        ],
        "apply_decision": [
            "Together",
            "SiliconFlow",
            "MoonshotAI",
            "Inceptron",
        ],
        "publish_issue": ["Together", "SiliconFlow", "MoonshotAI", "Inceptron"],
        "security_audit": [
            "Together",
            "DeepInfra",
            "Fireworks",
            "Parasail",
            "Inceptron",
        ],
        "intent_gate": [
            "Together",
            "DeepInfra",
            "Fireworks",
            "Parasail",
            "Inceptron",
        ],
        "planning_judge": [
            "Together",
            "DeepInfra",
            "Fireworks",
            "Parasail",
            "Inceptron",
        ],
        "syntax_lint": ["Together", "SiliconFlow", "MoonshotAI", "Inceptron"],
        "test_coverage": ["Together", "SiliconFlow", "MoonshotAI", "Inceptron"],
        "architecture": ["Together", "DeepInfra", "Fireworks", "Parasail", "Inceptron"],
        "security": ["DeepInfra", "SiliconFlow", "Novita", "Parasail", "DeepSeek"],
    }

    default_options = {
        "draft": {"thinking": "max"},
        "analyze_sources": {"thinking": "high"},
        "web_search": {"thinking": "none"},
        "propose_options": {"thinking": "max"},
        "security": {"thinking": "max"},
    }

    # Generous per-node output caps so large structured payloads (e.g. the
    # rewritten implementation-ready issue emitted by ``apply_decision``) are not
    # truncated at the provider default (#56). Overridable via config/factory.json.
    default_max_tokens = {
        "apply_decision": 16384,
        "evaluate_grade": 8192,
        "intent_gate": 8192,
        "planning_judge": 8192,
        "security_audit": 4096,
    }

    if overridden_model:
        # Environment override active => disable specific provider routing (set to None)
        model = overridden_model
        routing = None
        # Inherit temperature/options from factory if model matches, otherwise defaults
        factory_model_matches = (
            factory_cfg is not None and factory_cfg.model == overridden_model
        )
        if factory_model_matches:
            assert factory_cfg is not None  # narrows for type-checkers
            temperature = (
                factory_cfg.temperature if factory_cfg.temperature is not None else 0.0
            )
            options = factory_cfg.options
            max_tokens = factory_cfg.max_tokens
            timeout_seconds = factory_cfg.timeout_seconds
            max_retries = factory_cfg.max_retries
        else:
            temperature = 0.0
            options = default_options.get(phase_or_node)
            max_tokens = default_max_tokens.get(phase_or_node)
            timeout_seconds = None
            max_retries = None
    else:
        # Use factory config or fallback
        if factory_cfg:
            model = factory_cfg.model
            routing = factory_cfg.routing
            temperature = (
                factory_cfg.temperature if factory_cfg.temperature is not None else 0.0
            )
            options = factory_cfg.options
            max_tokens = (
                factory_cfg.max_tokens
                if factory_cfg.max_tokens is not None
                else default_max_tokens.get(phase_or_node)
            )
            timeout_seconds = factory_cfg.timeout_seconds
            max_retries = factory_cfg.max_retries
        else:
            model = default_models.get(phase_or_node, "z-ai/glm-5.2")
            routing = default_routing.get(phase_or_node)
            temperature = 0.0
            options = default_options.get(phase_or_node)
            max_tokens = default_max_tokens.get(phase_or_node)
            timeout_seconds = None
            max_retries = None

    return {
        "model": model,
        "routing": routing,
        "temperature": temperature,
        "options": options,
        "max_tokens": max_tokens,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
    }


def get_model(phase_or_node: str) -> str:
    """Resolves the LLM model name for a specific phase or refinement node with hierarchical fallbacks."""
    return resolve_model_config(phase_or_node)["model"]


class OpenRouterAnnotationChatOpenAI(ChatOpenAI):
    """``ChatOpenAI`` variant that preserves OpenRouter ``url_citation`` annotations.

    langchain-openai discards ``choices[].message.annotations`` while converting a
    Chat Completions response into an ``AIMessage``. OpenRouter surfaces web search
    results exclusively through these ``url_citation`` annotations, so they must be
    captured before the conversion drops them. This subclass copies the annotations
    (normalized to plain dicts) onto the resulting
    ``AIMessage.additional_kwargs["annotations"]``.

    This addresses *result parsing*, which is orthogonal to [ADR-0003](../docs/adr/0003-openrouter-server-tools-binding.md)'s
    decision: ADR-0003 rejected a custom ``bind_tools`` override for *tool binding*,
    whereas this override only captures provider-supplied metadata that the base
    integration throws away. The override is a no-op for responses without
    annotations, so it is safe for every refinement node — only ``web_search`` reads them.
    """

    def _create_chat_result(
        self,
        response: Any,
        generation_info: dict | None = None,
    ) -> Any:
        result = super()._create_chat_result(response, generation_info)
        try:
            message = (
                response["choices"][0]["message"]
                if isinstance(response, dict)
                else response.choices[0].message
            )
            raw_annotations = (
                message.get("annotations")
                if isinstance(message, dict)
                else getattr(message, "annotations", None)
            ) or []
            if raw_annotations and result.generations:
                normalized = [
                    ann.model_dump() if hasattr(ann, "model_dump") else ann
                    for ann in raw_annotations
                    if hasattr(ann, "model_dump") or isinstance(ann, dict)
                ]
                if normalized:
                    result.generations[0].message.additional_kwargs["annotations"] = (
                        normalized
                    )
        except Exception:
            # Annotation capture must never break the LLM call; the web_search node
            # handles the "no annotations" case explicitly via its status signal.
            pass
        return result


def get_llm(
    phase_or_node: str, max_tokens_override: Optional[int] = None
) -> "ChatOpenAI":
    cfg = resolve_model_config(phase_or_node)
    model_name = cfg["model"]
    routing = cfg["routing"]
    temperature = cfg["temperature"]
    options = cfg["options"]
    # An explicit override (used by the apply_decision retry loop to bump the
    # budget on truncation) takes precedence over the configured value.
    max_tokens = (
        max_tokens_override
        if max_tokens_override is not None
        else cfg.get("max_tokens")
    )

    api_key = os.getenv("OPENROUTER_API_KEY")

    extra_body: Dict[str, Any] = {}
    if routing:
        extra_body["provider"] = {
            "order": [r.lower() for r in routing],
            "allow_fallbacks": False,
        }
    if options:
        extra_body.update(options)

    # Transport-level timeout enforcement (ADR-0021). A bare float ``timeout``
    # only bounds the read phase and leaves ``connect`` unbounded; langchain-openai
    # / openai-python default to ``max_retries=2`` (3 attempts), which multiplies
    # the worst-case per-call budget and silently stacks sequential calls into a
    # multi-hour hang. We use an explicit ``httpx.Timeout`` with tight connect /
    # write / pool phases and disable SDK retries (isolation is app-level).
    timeout_seconds = (
        cfg["timeout_seconds"]
        if cfg.get("timeout_seconds") is not None
        else DEFAULT_LLM_TIMEOUT_SECONDS
    )
    max_retries = (
        cfg["max_retries"]
        if cfg.get("max_retries") is not None
        else DEFAULT_LLM_MAX_RETRIES
    )
    timeout_config = httpx.Timeout(
        connect=DEFAULT_LLM_CONNECT_TIMEOUT,
        read=timeout_seconds,
        write=DEFAULT_LLM_WRITE_TIMEOUT,
        pool=DEFAULT_LLM_POOL_TIMEOUT,
    )

    return OpenRouterAnnotationChatOpenAI(
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=api_key,
        use_responses_api=False,
        extra_body=extra_body or None,
        timeout=timeout_config,
        max_retries=max_retries,
    )
