from langchain_core.tools import tool
import requests
from urllib.parse import urlparse
import logging
from typing import Optional
import json
import base64
from planner.config import AppConfig

logger = logging.getLogger("planner.tools.research")


def extract_github_repo_from_url(url: str) -> Optional[str]:
    url = url.strip().lower()
    if "://" in url:
        url = url.split("://", 1)[1]
    if url.startswith("github.com/"):
        parts = url.split("/")
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
    return None


def is_domain_allowed(config: AppConfig, domain: str) -> bool:
    if not config.sources.strict:
        return True
    domain = domain.strip().lower()
    return domain in [d.strip().lower() for d in config.sources.domains if d]


def is_url_allowed(config: AppConfig, url: str) -> bool:
    if not config.sources.strict:
        return True
    url_lower = url.strip().lower()
    allowed_urls = [u.strip().lower() for u in config.sources.urls if u]
    if url_lower in allowed_urls:
        return True
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return is_domain_allowed(config, domain)


def is_repo_allowed(config: AppConfig, repo: str) -> bool:
    if not config.sources.strict:
        return True
    repo = repo.strip().lower()
    gh_repo = config.github_repository
    if gh_repo and repo == gh_repo.strip().lower():
        return True
    for u in config.sources.urls:
        extracted = extract_github_repo_from_url(u)
        if extracted and extracted.strip().lower() == repo:
            return True
    return False


def create_fetch_url_tool(config: AppConfig):
    @tool
    def fetch_url_content(url: str) -> str:
        """Fetches the text content of a given URL directly.

        Useful to read a specific documentation page or web resource.
        """
        if not is_url_allowed(config, url):
            return f"Error: Access to URL '{url}' is restricted under strict mode."

        try:
            # We do NOT use github session for general URLs to avoid leaking tokens
            headers = {"User-Agent": "agentic-planner-core/1.0"}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # Simple HTML tag removal if response is HTML, or just return text
            text = response.text
            # Basic cleanup of very long responses
            if len(text) > 50000:
                text = text[:50000] + "\n... [truncated due to length] ..."
            return text
        except Exception as e:
            return f"Error fetching URL '{url}': {e}"

    return fetch_url_content


def create_github_read_file_tool(config: AppConfig):
    @tool
    def read_github_file(repo: str, path: str, ref: Optional[str] = None) -> str:
        """Retrieves the raw content of a file from a GitHub repository.

        Parameters:
        - repo: The repository in 'owner/repo' format (e.g. 'LuisArteaga/agentic-planner-core').
        - path: The file path relative to the repository root (e.g. 'src/main.py').
        - ref: Optional branch, commit SHA, or tag (defaults to the default branch).
        """
        if not is_repo_allowed(config, repo):
            return (
                f"Error: Access to repository '{repo}' is restricted under strict mode."
            )

        try:
            session = config.get_github_session()
            url = f"https://api.github.com/repos/{repo}/contents/{path}"
            params = {}
            if ref:
                params["ref"] = ref

            res = session.get(url, params=params)
            if res.status_code == 404:
                return f"Error: File '{path}' or repository '{repo}' not found."
            res.raise_for_status()

            data = res.json()
            # GitHub returns base64 for file contents
            if (
                isinstance(data, dict)
                and data.get("encoding") == "base64"
                and "content" in data
            ):
                content = base64.b64decode(data["content"]).decode(
                    "utf-8", errors="replace"
                )
                if len(content) > 50000:
                    content = content[:50000] + "\n... [truncated due to length] ..."
                return content
            else:
                return (
                    f"Error: Path '{path}' is not a file or has unsupported encoding."
                )
        except Exception as e:
            return f"Error reading GitHub file '{path}' in repository '{repo}': {e}"

    return read_github_file


def create_github_list_issues_tool(config: AppConfig):
    @tool
    def list_github_issues(repo: str, state: str = "open", per_page: int = 10) -> str:
        """Lists issues from a GitHub repository.

        Parameters:
        - repo: The repository in 'owner/repo' format (e.g. 'owner/repo').
        - state: Filter by issue state: 'open', 'closed', or 'all' (default: 'open').
        - per_page: Number of issues to fetch (default: 10, max: 30).
        """
        if not is_repo_allowed(config, repo):
            return (
                f"Error: Access to repository '{repo}' is restricted under strict mode."
            )

        try:
            session = config.get_github_session()
            url = f"https://api.github.com/repos/{repo}/issues"
            params = {"state": state, "per_page": str(min(per_page, 30))}
            res = session.get(url, params=params)
            res.raise_for_status()

            issues = res.json()
            simplified = []
            for issue in issues:
                # PRs are also returned by issues API, skip them or label them
                is_pr = "pull_request" in issue
                simplified.append(
                    {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "user": issue.get("user", {}).get("login"),
                        "is_pull_request": is_pr,
                        "html_url": issue.get("html_url"),
                    }
                )
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return f"Error listing issues in repository '{repo}': {e}"

    return list_github_issues


def create_github_get_releases_tool(config: AppConfig):
    @tool
    def get_github_releases(repo: str, limit: int = 5) -> str:
        """Lists recent releases from a GitHub repository.

        Parameters:
        - repo: The repository in 'owner/repo' format.
        - limit: Number of releases to fetch (default: 5, max: 10).
        """
        if not is_repo_allowed(config, repo):
            return (
                f"Error: Access to repository '{repo}' is restricted under strict mode."
            )

        try:
            session = config.get_github_session()
            url = f"https://api.github.com/repos/{repo}/releases"
            params = {"per_page": str(min(limit, 10))}
            res = session.get(url, params=params)
            res.raise_for_status()

            releases = res.json()
            simplified = []
            for rel in releases:
                simplified.append(
                    {
                        "tag_name": rel.get("tag_name"),
                        "name": rel.get("name"),
                        "published_at": rel.get("published_at"),
                        "html_url": rel.get("html_url"),
                        "body": rel.get("body", "")[:500] + "..."
                        if rel.get("body")
                        else "",
                    }
                )
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return f"Error listing releases in repository '{repo}': {e}"

    return get_github_releases


def fetch_allowed_url(config: AppConfig, url: str) -> Optional[dict]:
    """Helper to fetch and parse allowed URLs directly (handling HTML and GitHub)."""
    import re

    url_lower = url.strip().lower()

    # 1. Handle GitHub URLs
    if "github.com/" in url_lower:
        repo = extract_github_repo_from_url(url)
        if repo and is_repo_allowed(config, repo):
            try:
                session = config.get_github_session()
                parsed = urlparse(url)
                path_parts = parsed.path.strip("/").split("/")

                # Check if it is a specific file blob
                if len(path_parts) > 3 and path_parts[2] == "blob":
                    branch = path_parts[3]
                    file_path = "/".join(path_parts[4:])
                    api_url = (
                        f"https://api.github.com/repos/{repo}/contents/{file_path}"
                    )
                    res = session.get(api_url, params={"ref": branch})
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, dict) and data.get("encoding") == "base64":
                            content = base64.b64decode(data["content"]).decode(
                                "utf-8", errors="replace"
                            )
                            return {
                                "title": f"GitHub File: {file_path} ({repo})",
                                "url": url,
                                "snippet": content[:2000],
                            }

                # Fallback to fetching README
                api_url = f"https://api.github.com/repos/{repo}/readme"
                res = session.get(api_url)
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, dict) and data.get("encoding") == "base64":
                        content = base64.b64decode(data["content"]).decode(
                            "utf-8", errors="replace"
                        )
                        return {
                            "title": f"GitHub README: {repo}",
                            "url": url,
                            "snippet": content[:2000],
                        }
            except Exception as e:
                logger.warning(f"Error fetching GitHub URL {url} via API: {e}")

    # 2. General HTTP Fetch
    if is_url_allowed(config, url):
        try:
            headers = {"User-Agent": "agentic-planner-core/1.0"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                text = res.text
                if "</html" in text.lower():
                    # Simple HTML tag and script removal
                    text = re.sub(r"<script.*?</script>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<.*?>", "", text, flags=re.DOTALL)
                    text = "\n".join(
                        [line.strip() for line in text.splitlines() if line.strip()]
                    )
                return {
                    "title": f"Direct URL: {url}",
                    "url": url,
                    "snippet": text[:2000],
                }
        except Exception as e:
            logger.warning(f"Error fetching URL {url}: {e}")

    return None
