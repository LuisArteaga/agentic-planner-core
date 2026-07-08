import os
import pathlib
import json
import functools
import logging
from typing import List, Optional, Dict, Any
import yaml
from pydantic import BaseModel, Field, model_validator
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from langchain_openai import ChatOpenAI

logger = logging.getLogger("planner.config")


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


class SourcesConfig(BaseModel):
    """Pydantic schema for parsing and validating sources.yaml configuration."""

    strict: bool = True
    urls: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    search: SearchParametersConfig = Field(default_factory=SearchParametersConfig)

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
    """System configuration class containing environment variables and yaml settings."""

    def __init__(
        self,
        sources_yaml_path: str = "config/sources.yaml",
        factory_json_path: str = "config/factory.json",
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

        # Parse and validate sources.yaml
        yaml_path = pathlib.Path(sources_yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {sources_yaml_path}"
            )

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            raise ValueError(f"Invalid YAML format in {sources_yaml_path}: {e}")

        # Validate parsed data via Pydantic
        try:
            self.sources = SourcesConfig.model_validate(data)
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}")

        # Parse and validate factory.json
        _load_factory_config(factory_json_path)

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


class ModelConfig(BaseModel):
    """Configuration for a specific LLM model used by a phase, node, or judge."""

    model: str
    routing: Optional[List[str]] = None
    temperature: Optional[float] = None
    options: Optional[Dict[str, Any]] = None


class FactoryConfig(BaseModel):
    """Central model configuration schema loaded from config/factory.json."""

    factory_version: str
    cli_orchestration: Dict[str, ModelConfig]
    refine_graph_nodes: Dict[str, ModelConfig]
    ci_cd_pr_judges: Dict[str, ModelConfig]


@functools.lru_cache(maxsize=1)
def _load_factory_config(
    filepath: str = "config/factory.json",
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

    if overridden_model:
        # Environment override active => disable specific provider routing (set to None)
        model = overridden_model
        routing = None
        # Inherit temperature/options from factory if model matches, otherwise defaults
        if factory_cfg and factory_cfg.model == overridden_model:
            temperature = (
                factory_cfg.temperature if factory_cfg.temperature is not None else 0.0
            )
            options = factory_cfg.options
        else:
            temperature = 0.0
            options = default_options.get(phase_or_node)
    else:
        # Use factory config or fallback
        if factory_cfg:
            model = factory_cfg.model
            routing = factory_cfg.routing
            temperature = (
                factory_cfg.temperature if factory_cfg.temperature is not None else 0.0
            )
            options = factory_cfg.options
        else:
            model = default_models.get(phase_or_node, "z-ai/glm-5.2")
            routing = default_routing.get(phase_or_node)
            temperature = 0.0
            options = default_options.get(phase_or_node)

    return {
        "model": model,
        "routing": routing,
        "temperature": temperature,
        "options": options,
    }


def get_model(phase_or_node: str) -> str:
    """Resolves the LLM model name for a specific phase or refinement node with hierarchical fallbacks."""
    return resolve_model_config(phase_or_node)["model"]


def get_llm(phase_or_node: str) -> "ChatOpenAI":
    cfg = resolve_model_config(phase_or_node)
    model_name = cfg["model"]
    routing = cfg["routing"]
    temperature = cfg["temperature"]
    options = cfg["options"]

    api_key = os.getenv("OPENROUTER_API_KEY")

    model_kwargs: Dict[str, Any] = {}
    extra_body = {}
    if routing:
        extra_body["provider"] = {
            "order": [r.lower() for r in routing],
            "allow_fallbacks": False,
        }
    if options:
        extra_body.update(options)

    if extra_body:
        model_kwargs["extra_body"] = extra_body

    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=api_key,
        use_responses_api=False,
        model_kwargs=model_kwargs,
        timeout=600.0,  # Prevent indefinite hangs on OpenRouter API calls while allowing long reasoning generations
    )
