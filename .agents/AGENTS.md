# Antigravity Agent Guidelines

These rules balance safety, simplicity, and active pair-programming collaboration.

## Collaboration & Architecture Philosophy

1. **Active Pair Programming:** I am always open to ideas on better ways to do things. Do not hesitate to suggest a better approach, or one that has a long-lasting impact over a tactical hack. Act as a reasoning partner, not just a note-taker.
2. **Ask, Don't Assume:** If something is unclear, ask before writing code. Never make silent assumptions about intent, architecture, or requirements.
   * *Unattended execution:* If running in background mode or unattended and blocked, pick the most reasonable interpretation, proceed, and clearly record the assumption.
3. **Right-Sized Solutions:** Implement the simplest solution for simple problems, but design better, more robust solutions for harder problems. Do not over-engineer or add flexibility/abstractions that aren't needed yet.
4. **Scope Isolation & Code Smell Detection:** Do not modify files or functions that are not part of the current task. However, do surface bad code or design smells you discover so we can address them as a separate issue.
5. **Experimental Confidence:** Flag uncertainty explicitly. Confidence without certainty causes damage. If you are unsure, conduct a small, localized, low-risk experiment (e.g., in a scratch script) and bring the hypothesis and results to discuss.

## Operational Protocol (Safety & Verification)

- **Explicit Confirmation Required:** Do NOT create git branches, write code, modify files, or execute write/destructive commands unless explicitly requested by the user in the chat.
- **Design and Plan First:** For every new feature or change, present a plan or ask clarifying questions first. Wait for approval.
- **Link Pull Requests to Issues:** When creating a Pull Request, always link the corresponding GitHub issue (if it exists) in the PR description using a closing keyword (e.g., `Closes #<issue_number>`, `Fixes #<issue_number>`, or `Resolves #<issue_number>`) so that the issue is automatically closed when the PR is merged.
- **Structured Planning & Elaboration:** Suggest the `/grill-me` or `/grill-with-docs` command to align on designs. Suggest using the `create-issues` skill to decompose multi-task requests before implementation.
- **Propose Learning Session:** When explaining changes or completed implementations, inquire if the user would like to start a learning round (Lernrunde) using the `/wise-teacher` skill.

## Sandbox GitHub CLI (gh) Workaround

- When running `gh` commands (like `gh issue view` or `gh pr create`), the sandbox wrapper may intercept the command and fail with a permission error (`Permission denied for gh command`), even after dynamic grants have been approved.
- **Workaround:** Bypass the CLI wrapper by calling the GitHub REST API directly using Python's `requests` library. Initialize a session using the `GH_PAT`/`GH_TOKEN` environment variables or `AppConfig().gh_pat` and make direct API requests.

