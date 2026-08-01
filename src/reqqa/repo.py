"""Per-project git repository — reqoach's lifecycle responsibility.

See `documents/project_git_repo_requirement.md`. On project creation reqoach creates a
LOCAL git repo per project and scaffolds the single-owner layout each agent writes into.
The GitHub REMOTE is NOT created here — that needs the user's credentials and choices, so
it is recorded as a **pending action** surfaced in the UI for the user to complete.

Local automation now; remote-on-demand later. No git history operations happen on any repo
but the project's own freshly-created one.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

#: Where project repos live. A shared volume in deployment; env-overridable.
REPOS_ROOT = os.environ.get("PROJECT_REPOS_ROOT", os.path.expanduser("~/env/project-repos"))

#: Single-owner areas — one agent per top-level dir, so no two agents ever write the same
#: path and there are no merge races on a shared tree.
_LAYOUT = ("requirements", "architecture", "plans", "code")

_GITIGNORE = """\
# Large/derived assets are NOT committed — handled by the asset conventions, not git.
*.jar
*.gguf
*.bin
*.pt
*.onnx
*.zip
*.tar
*.tar.gz
*.pdf
__pycache__/
*.pyc
.venv/
node_modules/
"""


class RepoError(RuntimeError):
    pass


@dataclass
class PendingAction:
    """A step the user must complete (the local side is automated; this is what isn't)."""
    kind: str                       # e.g. "create_github_remote"
    title: str
    detail: str
    done: bool = False


@dataclass
class ProjectRepo:
    project_id: str
    path: str
    pending: list[PendingAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"project_id": self.project_id, "path": self.path,
                "pending_actions": [a.__dict__ for a in self.pending]}


def repo_path(project_id: str) -> str:
    return os.path.join(REPOS_ROOT, project_id)


def _git(path: str, *args: str) -> str:
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RepoError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def create_local_repo(project_id: str, name: str,
                      github_owner: str | None = None) -> ProjectRepo:
    """Create (idempotently) the project's local git repo with the standard layout, an
    initial commit, and a pending action to create the GitHub remote.

    Returns the ProjectRepo. Safe to call again — an existing repo is returned unchanged.
    """
    path = repo_path(project_id)
    already = os.path.isdir(os.path.join(path, ".git"))
    os.makedirs(path, exist_ok=True)

    if not already:
        subprocess.run(["git", "init", "-q", "-b", "main", path], check=True)
        for area in _LAYOUT:
            d = os.path.join(path, area)
            os.makedirs(d, exist_ok=True)
            # .gitkeep so empty areas are tracked before an agent writes into them.
            open(os.path.join(d, ".gitkeep"), "a").close()
        with open(os.path.join(path, "README.md"), "w") as f:
            f.write(f"# {name}\n\nProject `{project_id}` — pipeline artifacts.\n\n"
                    "- `requirements/` — Analyst\n- `architecture/` — Architect\n"
                    "- `plans/` — Planner\n- `code/` — Builder\n")
        with open(os.path.join(path, ".gitignore"), "w") as f:
            f.write(_GITIGNORE)
        _git(path, "add", "-A")
        # Author identity is the platform, not a person — this is an automated commit.
        _git(path, "-c", "user.name=reqoach", "-c", "user.email=reqoach@logus2k.com",
             "commit", "-q", "-m", f"Initialise project {name} ({project_id})")

    repo = ProjectRepo(project_id=project_id, path=path)
    if not _has_remote(path):
        suggested = f"{github_owner}/{_slug(name)}" if github_owner else _slug(name)
        repo.pending.append(PendingAction(
            kind="create_github_remote",
            title="Create the GitHub remote for this project",
            detail=(f"Create a (private) GitHub repository, then set it as the remote and "
                    f"push. Suggested name: {suggested}. The local repo is ready at {path}."),
        ))
    _save_meta(repo)
    return repo


def _has_remote(path: str) -> bool:
    try:
        return bool(_git(path, "remote"))
    except RepoError:
        return False


def _slug(name: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-") or "project"


def _meta_path(path: str) -> str:
    return os.path.join(path, ".reqoach", "repo.json")


def _save_meta(repo: ProjectRepo) -> None:
    os.makedirs(os.path.dirname(_meta_path(repo.path)), exist_ok=True)
    with open(_meta_path(repo.path), "w") as f:
        json.dump(repo.to_dict(), f, indent=2)


def get_repo(project_id: str) -> ProjectRepo | None:
    """Load a project's repo record (path + pending actions), or None if not created."""
    path = repo_path(project_id)
    mp = _meta_path(path)
    if not os.path.isfile(mp):
        return None
    d = json.load(open(mp))
    return ProjectRepo(project_id=d["project_id"], path=d["path"],
                       pending=[PendingAction(**a) for a in d.get("pending_actions", [])])


def pending_actions(project_id: str) -> list[dict]:
    """What the UI shows the user for this project (unfinished steps)."""
    repo = get_repo(project_id)
    return [a.__dict__ for a in (repo.pending if repo else []) if not a.done]
