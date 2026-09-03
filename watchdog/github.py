from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str, owner: str, owner_type: str = "user", template_repo: str | None = None):
        self.token = token
        self.owner = owner
        self.owner_type = owner_type
        self.template_repo = template_repo

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"https://api.github.com{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "project-watchdog",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise GitHubError(f"GitHub API returned {error.code}: {detail}") from error

    def repository(self, full_name: str) -> dict:
        owner, name = full_name.split("/", 1)
        return self._request("GET", f"/repos/{quote(owner)}/{quote(name)}")

    def latest_commit_message(self, full_name: str) -> str | None:
        owner, name = full_name.split("/", 1)
        try:
            commits = self._request("GET", f"/repos/{quote(owner)}/{quote(name)}/commits?per_page=1")
        except GitHubError as error:
            # GitHub returns 409 for a repository with no commits.
            if "returned 409" in str(error):
                return None
            raise
        if not commits:
            return None
        message = commits[0].get("commit", {}).get("message", "")
        return message.splitlines()[0].strip() or None

    def create_repository(self, name: str, description: str = "") -> dict:
        if self.template_repo:
            template_owner, template_name = self.template_repo.split("/", 1)
            return self._request(
                "POST",
                f"/repos/{quote(template_owner)}/{quote(template_name)}/generate",
                {"owner": self.owner, "name": name, "description": description, "private": True},
            )
        endpoint = f"/orgs/{quote(self.owner)}/repos" if self.owner_type == "org" else "/user/repos"
        return self._request("POST", endpoint, {"name": name, "description": description, "private": True})
