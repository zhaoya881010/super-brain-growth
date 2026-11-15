from __future__ import annotations

import base64
import difflib
import json
import re
import shutil
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SKILLS_PATH = DATA_DIR / "skills.json"
TASKS_PATH = DATA_DIR / "tasks.json"
REPOS_PATH = DATA_DIR / "repos.json"
PROPOSALS_PATH = DATA_DIR / "proposals.json"
SANDBOX_ROOT = BASE_DIR / "sandbox" / "worktrees"
MAX_PROPOSAL_FILE_BYTES = 1_000_000
MAX_PROPOSAL_TOTAL_BYTES = 5_000_000
MAX_PROPOSAL_FILES = 100
PROTECTED_PATH_PARTS = {
    ".git",
    ".github",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "data",
    "node_modules",
    "sandbox",
    "venv",
}
GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.-]+)/?$"
)

app = FastAPI(title="Super Brain Growth", version="0.3.0")


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (SKILLS_PATH, TASKS_PATH, REPOS_PATH, PROPOSALS_PATH):
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")


def load_json(path: Path) -> list[dict[str, Any]]:
    ensure_data_files()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def save_json(path: Path, payload: list[dict[str, Any]]) -> None:
    ensure_data_files()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def validate_proposal_path(raw_path: str) -> str:
    if (
        "\x00" in raw_path
        or "\\" in raw_path
        or ":" in raw_path
        or raw_path.startswith("/")
        or any(part in {"", ".", ".."} for part in raw_path.split("/"))
    ):
        raise HTTPException(status_code=422, detail=f"Unsafe relative path: {raw_path!r}")

    path = PurePosixPath(raw_path)
    if path.is_absolute() or any(part.casefold() in PROTECTED_PATH_PARTS for part in path.parts):
        raise HTTPException(status_code=422, detail=f"Protected path: {raw_path!r}")
    if path.suffix.casefold() not in {".py", ".json"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type for {raw_path!r}; only .py and .json are allowed",
        )
    if any(part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL"} for part in path.parts):
        raise HTTPException(status_code=422, detail=f"Unsupported path component: {raw_path!r}")
    if any(re.fullmatch(r"(COM|LPT)[1-9]", part.split(".")[0], re.IGNORECASE) for part in path.parts):
        raise HTTPException(status_code=422, detail=f"Unsupported path component: {raw_path!r}")
    return path.as_posix()


def reject_symlink_components(path: Path) -> None:
    try:
        relative = path.relative_to(BASE_DIR)
    except ValueError:
        raise HTTPException(status_code=422, detail="Path escapes the project directory")

    current = BASE_DIR
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=422, detail="Symlink paths are not allowed")


def ensure_directory(path: Path) -> None:
    reject_symlink_components(path)
    relative = path.relative_to(BASE_DIR)
    current = BASE_DIR
    for part in relative.parts:
        current = current / part
        if current.exists():
            if not current.is_dir():
                raise HTTPException(status_code=422, detail="Sandbox path is not a directory")
        else:
            current.mkdir()


def find_task(task_id: str) -> dict[str, Any]:
    task = next((item for item in load_json(TASKS_PATH) if item.get("id") == task_id), None)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not re.fullmatch(r"[a-f0-9]{32}", task_id):
        raise HTTPException(status_code=422, detail="Task ID cannot be used as a sandbox directory")
    return task


def get_task_proposals(task_id: str) -> list[dict[str, Any]]:
    return [proposal for proposal in load_json(PROPOSALS_PATH) if proposal.get("task_id") == task_id]


def get_proposal(task_id: str, proposal_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proposals = load_json(PROPOSALS_PATH)
    for proposal in proposals:
        if proposal.get("id") == proposal_id and proposal.get("task_id") == task_id:
            return proposals, proposal
    raise HTTPException(status_code=404, detail="Proposal not found")


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=10, max_length=2000)
    source_url: str = Field(..., min_length=1, max_length=500)
    status: str = "proposed"
    tags: list[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=10, max_length=4000)
    status: str = "proposed"
    source_url: str | None = None
    capability: str | None = None
    verification: list[str] = Field(default_factory=list, max_length=50)


class TaskStatusUpdate(BaseModel):
    status: Literal["proposed", "in_progress", "in_review", "approved", "rejected", "completed"]


class VerificationStatusUpdate(BaseModel):
    status: Literal["pending", "in_progress", "passed", "failed"]


class ProposalFile(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    content: str


class ProposalCreate(BaseModel):
    files: list[ProposalFile] = Field(..., min_length=1, max_length=MAX_PROPOSAL_FILES)


class ReviewDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class RepoCreate(BaseModel):
    url: str = Field(..., min_length=1, max_length=500)
    purpose: str = Field(default="", max_length=1000)


class ImprovementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=10, max_length=4000)


def github_request(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "super-brain-growth",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise HTTPException(status_code=404, detail="GitHub repository not found")
        if error.code == 403:
            raise HTTPException(
                status_code=503,
                detail="GitHub API rate limit or access restriction; try again later",
            )
        raise HTTPException(status_code=502, detail=f"GitHub API returned {error.code}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="Could not reach GitHub API")


def analyze_github_repo(owner: str, name: str) -> dict[str, Any]:
    metadata = github_request(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}")
    readme_text = ""
    try:
        readme = github_request(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/readme")
        if readme.get("encoding") == "base64":
            raw = base64.b64decode(readme.get("content", ""))
            readme_text = raw.decode("utf-8", errors="replace")[:12000]
    except HTTPException as error:
        if error.status_code != 404:
            raise

    license_info = metadata.get("license") or {}
    return {
        "full_name": metadata.get("full_name", f"{owner}/{name}"),
        "url": metadata.get("html_url", f"https://github.com/{owner}/{name}"),
        "description": metadata.get("description"),
        "stars": metadata.get("stargazers_count", 0),
        "language": metadata.get("language"),
        "license": license_info.get("spdx_id"),
        "topics": metadata.get("topics", []),
        "default_branch": metadata.get("default_branch"),
        "archived": metadata.get("archived", False),
        "updated_at": metadata.get("updated_at"),
        "readme_excerpt": readme_text[:4000],
        "analysis_note": (
            "Metadata and README only. Source code has not been downloaded, executed, "
            "security-audited, or verified. Review the license and code before reuse."
        ),
    }


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    skills = load_json(SKILLS_PATH)
    tasks = load_json(TASKS_PATH)
    repos = load_json(REPOS_PATH)
    html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Super Brain Growth</title>
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }}
          .card {{ background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 1rem; margin-top: 1rem; }}
          a {{ color: #7dd3fc; }}
          .muted {{ color: #94a3b8; }}
        </style>
      </head>
      <body>
        <h1>Super Brain Growth</h1>
        <p class="muted">A safe, reviewable growth loop that learns from public GitHub sources.</p>
        <div class="grid">
          <div class="card"><h2>Skills</h2><p>{len(skills)}</p></div>
          <div class="card"><h2>Growth tasks</h2><p>{len(tasks)}</p></div>
          <div class="card"><h2>GitHub projects</h2><p>{len(repos)}</p></div>
        </div>
        <div class="card">
          <h3>What this version does</h3>
          <ul>
            <li>Register public GitHub repositories by URL.</li>
            <li>Fetch metadata and README excerpt through the GitHub REST API.</li>
            <li>Create isolated code proposals with static Python/JSON validation and human review.</li>
            <li>Keep a clear safety boundary: no code is cloned or executed from external repositories.</li>
          </ul>
          <p><a href="/docs">Open API docs</a> · <a href="/api/skills">Skills API</a> · <a href="/api/tasks">Tasks API</a> · <a href="/api/repos">Repos API</a></p>
        </div>
      </body>
    </html>
    """
    return html


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "super-brain-growth"}


@app.get("/api/skills")
def list_skills() -> list[dict[str, Any]]:
    return load_json(SKILLS_PATH)


@app.post("/api/skills")
def create_skill(payload: SkillCreate) -> dict[str, Any]:
    skills = load_json(SKILLS_PATH)
    skill = {"id": uuid.uuid4().hex, **payload.model_dump()}
    skills.append(skill)
    save_json(SKILLS_PATH, skills)
    return skill


@app.get("/api/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return load_json(TASKS_PATH)


@app.post("/api/tasks")
def create_task(payload: TaskCreate) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    task = {
        "id": uuid.uuid4().hex,
        **payload.model_dump(exclude={"verification"}),
        "verification": [
            {"id": uuid.uuid4().hex, "description": step, "status": "pending"}
            for step in payload.verification
        ],
    }
    tasks.append(task)
    save_json(TASKS_PATH, tasks)
    return task


@app.patch("/api/tasks/{task_id}/status")
def update_task_status(task_id: str, payload: TaskStatusUpdate) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = payload.status
            save_json(TASKS_PATH, tasks)
            return task
    raise HTTPException(status_code=404, detail="Task not found")


@app.patch("/api/tasks/{task_id}/verification/{step_id}")
def update_verification_status(
    task_id: str, step_id: str, payload: VerificationStatusUpdate
) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    for task in tasks:
        if task.get("id") != task_id:
            continue
        for step in task.get("verification", []):
            if step.get("id") == step_id:
                step["status"] = payload.status
                save_json(TASKS_PATH, tasks)
                return task
        raise HTTPException(status_code=404, detail="Verification step not found")
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: str) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "approved"
            save_json(TASKS_PATH, tasks)
            return task
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/tasks/{task_id}/proposals", status_code=201)
def create_proposal(task_id: str, payload: ProposalCreate) -> dict[str, Any]:
    find_task(task_id)
    files_by_path: dict[str, ProposalFile] = {}
    seen_paths: set[str] = set()
    total_size = 0
    for file in payload.files:
        relative_path = validate_proposal_path(file.path)
        path_key = relative_path.casefold()
        if path_key in seen_paths:
            raise HTTPException(status_code=422, detail=f"Duplicate path: {relative_path!r}")
        seen_paths.add(path_key)
        try:
            content_size = len(file.content.encode("utf-8"))
        except UnicodeEncodeError:
            raise HTTPException(status_code=422, detail=f"File is not valid UTF-8: {relative_path!r}")
        if content_size > MAX_PROPOSAL_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {MAX_PROPOSAL_FILE_BYTES}-byte limit: {relative_path!r}",
            )
        total_size += content_size
        if total_size > MAX_PROPOSAL_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Proposal exceeds the {MAX_PROPOSAL_TOTAL_BYTES}-byte total limit",
            )
        files_by_path[relative_path] = file

    checks: list[dict[str, Any]] = []
    diff_lines: list[str] = []
    file_records: list[dict[str, Any]] = []
    added_files = 0
    modified_files = 0
    additions = 0
    deletions = 0

    for relative_path, file in files_by_path.items():
        project_path = BASE_DIR.joinpath(*PurePosixPath(relative_path).parts)
        reject_symlink_components(project_path)
        if project_path.exists() and not project_path.is_file():
            raise HTTPException(status_code=422, detail=f"Proposal path is not a file: {relative_path!r}")
        try:
            original = project_path.read_text(encoding="utf-8") if project_path.exists() else ""
        except (OSError, UnicodeDecodeError):
            raise HTTPException(
                status_code=422, detail=f"Could not safely read the existing file: {relative_path!r}"
            )

        checker = "python_compile" if project_path.suffix.casefold() == ".py" else "json_parse"
        try:
            if checker == "python_compile":
                compile(file.content, relative_path, "exec")
            else:
                json.loads(file.content)
            checks.append(
                {"path": relative_path, "checker": checker, "passed": True, "detail": "Static check passed"}
            )
        except SyntaxError as error:
            checks.append(
                {
                    "path": relative_path,
                    "checker": checker,
                    "passed": False,
                    "detail": f"SyntaxError on line {error.lineno}: {error.msg}",
                }
            )
        except json.JSONDecodeError as error:
            checks.append(
                {
                    "path": relative_path,
                    "checker": checker,
                    "passed": False,
                    "detail": f"JSON error on line {error.lineno}, column {error.colno}: {error.msg}",
                }
            )

        if project_path.exists():
            modified_files += 1
        else:
            added_files += 1
        current_diff = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                file.content.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
        diff_lines.extend(current_diff)
        additions += sum(line.startswith("+") and not line.startswith("+++") for line in current_diff)
        deletions += sum(line.startswith("-") and not line.startswith("---") for line in current_diff)
        file_records.append(
            {
                "path": relative_path,
                "size_bytes": len(file.content.encode("utf-8")),
                "checker": checker,
            }
        )

    validation_status = "passed" if all(check["passed"] for check in checks) else "failed"
    summary = {
        "file_count": len(file_records),
        "added_files": added_files,
        "modified_files": modified_files,
        "additions": additions,
        "deletions": deletions,
        "validation_status": validation_status,
        "text": (
            f"{len(file_records)} file(s): {added_files} added, {modified_files} modified; "
            f"{additions} line(s) added, {deletions} removed. "
            f"Static validation {validation_status}."
        ),
    }

    proposal_id = uuid.uuid4().hex
    task_sandbox = SANDBOX_ROOT / task_id
    proposal_dir = task_sandbox / proposal_id
    ensure_directory(task_sandbox)
    ensure_directory(proposal_dir)
    try:
        for relative_path, file in files_by_path.items():
            destination = proposal_dir.joinpath(*PurePosixPath(relative_path).parts)
            ensure_directory(destination.parent)
            reject_symlink_components(destination)
            with destination.open("x", encoding="utf-8", newline="") as output:
                output.write(file.content)
    except HTTPException:
        shutil.rmtree(proposal_dir, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(proposal_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not store proposal files: {error}")

    proposal = {
        "id": proposal_id,
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending",
        "validation_status": validation_status,
        "static_checks": checks,
        "files": file_records,
        "sandbox_path": proposal_dir.relative_to(BASE_DIR).as_posix(),
        "diff": "".join(diff_lines),
        "summary": summary,
        "decision": None,
    }
    proposals = load_json(PROPOSALS_PATH)
    proposals.append(proposal)
    save_json(PROPOSALS_PATH, proposals)
    return proposal


@app.get("/api/tasks/{task_id}/proposals")
def list_proposals(task_id: str) -> list[dict[str, Any]]:
    find_task(task_id)
    return get_task_proposals(task_id)


@app.get("/api/tasks/{task_id}/proposals/{proposal_id}")
def read_proposal(task_id: str, proposal_id: str) -> dict[str, Any]:
    find_task(task_id)
    _, proposal = get_proposal(task_id, proposal_id)
    return proposal


@app.post("/api/tasks/{task_id}/proposals/{proposal_id}/approve")
def approve_proposal(
    task_id: str, proposal_id: str, payload: ReviewDecision | None = None
) -> dict[str, Any]:
    find_task(task_id)
    proposals, proposal = get_proposal(task_id, proposal_id)
    if proposal.get("validation_status") != "passed":
        raise HTTPException(status_code=409, detail="Proposal failed static validation and cannot be approved")
    if proposal.get("review_status") != "pending":
        raise HTTPException(status_code=409, detail="Proposal already has a review decision")
    proposal["review_status"] = "approved"
    proposal["decision"] = {
        "status": "approved",
        "reason": payload.reason if payload else None,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "effect": "Recorded only; no merge or deployment performed.",
    }
    save_json(PROPOSALS_PATH, proposals)
    return proposal


@app.post("/api/tasks/{task_id}/proposals/{proposal_id}/reject")
def reject_proposal(
    task_id: str, proposal_id: str, payload: ReviewDecision | None = None
) -> dict[str, Any]:
    find_task(task_id)
    proposals, proposal = get_proposal(task_id, proposal_id)
    if proposal.get("review_status") != "pending":
        raise HTTPException(status_code=409, detail="Proposal already has a review decision")
    proposal["review_status"] = "rejected"
    proposal["decision"] = {
        "status": "rejected",
        "reason": payload.reason if payload else None,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "effect": "Recorded only; no merge or deployment performed.",
    }
    save_json(PROPOSALS_PATH, proposals)
    return proposal


@app.get("/api/repos")
def list_repos() -> list[dict[str, Any]]:
    return load_json(REPOS_PATH)


@app.post("/api/repos", status_code=201)
def add_repo(payload: RepoCreate) -> dict[str, Any]:
    match = GITHUB_REPO_URL.fullmatch(payload.url.strip())
    if not match:
        raise HTTPException(
            status_code=422,
            detail="Use a public repository URL in the form https://github.com/owner/repo",
        )
    owner, name = match.group("owner"), match.group("repo")
    name = name.removesuffix(".git")
    url = f"https://github.com/{owner}/{name}"
    repos = load_json(REPOS_PATH)
    existing = next((repo for repo in repos if repo["url"].lower() == url.lower()), None)
    if existing:
        return existing
    repo = {
        "id": uuid.uuid4().hex,
        "full_name": f"{owner}/{name}",
        "url": url,
        "purpose": payload.purpose.strip(),
        "status": "registered",
        "analysis": None,
    }
    repos.append(repo)
    save_json(REPOS_PATH, repos)
    return repo


@app.post("/api/repos/{repo_id}/analyze")
def analyze_repo(repo_id: str) -> dict[str, Any]:
    repos = load_json(REPOS_PATH)
    for repo in repos:
        if repo["id"] == repo_id:
            match = GITHUB_REPO_URL.fullmatch(repo["url"])
            if not match:
                raise HTTPException(status_code=422, detail="Stored repository URL is invalid")
            analysis = analyze_github_repo(match.group("owner"), match.group("repo"))
            repo["analysis"] = analysis
            repo["status"] = "analyzed"
            save_json(REPOS_PATH, repos)
            return analysis
    raise HTTPException(status_code=404, detail="Repository not found")


@app.post("/api/repos/{repo_id}/improvements", status_code=201)
def create_improvement(repo_id: str, payload: ImprovementCreate) -> dict[str, Any]:
    repos = load_json(REPOS_PATH)
    repo = next((item for item in repos if item["id"] == repo_id), None)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    tasks = load_json(TASKS_PATH)
    task = {
        "id": uuid.uuid4().hex,
        "title": payload.title,
        "description": payload.description,
        "status": "proposed",
        "source_url": repo["url"],
        "capability": "repository_improvement",
        "repository_id": repo_id,
        "safety_note": "Proposal only. No source was cloned, executed, or modified.",
    }
    tasks.append(task)
    save_json(TASKS_PATH, tasks)
    return task


@app.post("/api/grow")
def propose_growth(idea: dict[str, str]) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    task = {
        "id": uuid.uuid4().hex,
        "title": idea.get("title") or "New capability idea",
        "description": idea.get("description") or "A candidate capability to learn from GitHub sources.",
        "status": "proposed",
        "source_url": idea.get("source_url"),
        "capability": "growth_candidate",
    }
    tasks.append(task)
    save_json(TASKS_PATH, tasks)
    return task


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)


