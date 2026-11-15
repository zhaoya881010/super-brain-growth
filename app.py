from __future__ import annotations

import base64
import json
import re
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SKILLS_PATH = DATA_DIR / "skills.json"
TASKS_PATH = DATA_DIR / "tasks.json"
REPOS_PATH = DATA_DIR / "repos.json"
GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.-]+)/?$"
)

app = FastAPI(title="Super Brain Growth", version="0.2.0")


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (SKILLS_PATH, TASKS_PATH, REPOS_PATH):
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
            <li>Create reviewable improvement tasks.</li>
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
    task = {"id": uuid.uuid4().hex, **payload.model_dump()}
    tasks.append(task)
    save_json(TASKS_PATH, tasks)
    return task


@app.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: str) -> dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = "approved"
            save_json(TASKS_PATH, tasks)
            return task
    raise HTTPException(status_code=404, detail="Task not found")


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


