import os
import pathlib
from typing import List
import yaml
from pydantic import BaseModel, Field, model_validator
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter


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


class SourcesConfig(BaseModel):
    """Pydantic schema for parsing and validating sources.yaml configuration."""

    strict: bool = True
    repositories: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_strict_sources(self) -> "SourcesConfig":
        if self.strict and not self.repositories and not self.domains:
            raise ValueError(
                "Strict-mode is enabled (strict: true), but both 'repositories' "
                "and 'domains' are empty. At least one source must be defined."
            )
        return self


class AppConfig:
    """System configuration class containing environment variables and yaml settings."""

    def __init__(self, sources_yaml_path: str = "config/sources.yaml"):
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
                self.github_workspace = str(
                    (project_root / ".workspaces" / workspace_path).resolve()
                )
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
        return session
