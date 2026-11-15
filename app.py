from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Any, Dict, List, Literal
import json

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SKILLS_PATH = DATA_DIR / "skills.json"
TASKS_PATH = DATA_DIR / "tasks.json"

app = FastAPI(title="Super Brain Growth MVP", version="0.1.0")


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SKILLS_PATH.exists():
        SKILLS_PATH.write_text(json.dumps([], indent=2), encoding="utf-8")
    if not TASKS_PATH.exists():
        TASKS_PATH.write_text(json.dumps([], indent=2), encoding="utf-8")


def load_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_json(path: Path, payload: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


ensure_data_files()


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=2)
    description: str = Field(..., min_length=10)
    source_url: str = Field(...)
    status: Literal["proposed", "verified", "approved"] = "proposed"
    tags: List[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=2)
    description: str = Field(..., min_length=10)
    status: Literal["proposed", "in_progress", "approved", "done"] = "proposed"
    source_url: str | None = None
    capability: str | None = None


@app.get("/")
def root() -> str:
    skills = load_json(SKILLS_PATH)
    tasks = load_json(TASKS_PATH)
    approved_count = sum(1 for task in tasks if task.get("status") == "approved")
    approved_skills = sum(1 for skill in skills if skill.get("status") == "approved")
    html = f"""
    <html>
      <head>
        <title>Super Brain Growth MVP</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1rem; }}
          .card {{ background: #111827; padding: 1rem 1.2rem; border-radius: 12px; border: 1px solid #2b374a; box-shadow: 0 8px 24px rgba(15,23,42,0.25); }}
          .muted {{ color: #94a3b8; }}
          a {{ color: #7dd3fc; }}
          ul {{ padding-left: 1rem; }}
        </style>
      </head>
      <body>
        <h1>Super Brain Growth MVP</h1>
        <p class="muted">A self-growing intelligence system built around GitHub sourceability and human approval.</p>
        <div class="grid">
          <div class="card">
            <h2>Skills</h2>
            <p>{len(skills)}</p>
          </div>
          <div class="card">
            <h2>Growth Tasks</h2>
            <p>{len(tasks)}</p>
          </div>
          <div class="card">
            <h2>Approved Tasks</h2>
            <p>{approved_count}</p>
          </div>
          <div class="card">
            <h2>Approved Skills</h2>
            <p>{approved_skills}</p>
          </div>
        </div>
        <div class="card" style="margin-top: 1rem;">
          <h3>System intent</h3>
          <ul>
            <li>Discover candidate capabilities from GitHub sources.</li>
            <li>Convert promising ideas into skills and tasks.</li>
            <li>Validate in isolated steps before approval.</li>
            <li>Keep a traceable record of growth and feedback.</li>
          </ul>
          <p><a href="/docs">Open API docs</a> | <a href="/api/skills">Skills API</a> | <a href="/api/tasks">Tasks API</a></p>
        </div>
      </body>
    </html>
    """
    return html


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "super-brain-growth-mvp"}


@app.get("/api/skills")
def list_skills() -> List[Dict[str, Any]]:
    ensure_data_files()
    return load_json(SKILLS_PATH)


@app.post("/api/skills")
def create_skill(payload: SkillCreate) -> Dict[str, Any]:
    skills = load_json(SKILLS_PATH)
    skill = {
        "id": f"skill-{len(skills) + 1}",
        "name": payload.name,
        "description": payload.description,
        "source_url": payload.source_url,
        "status": payload.status,
        "tags": payload.tags,
    }
    skills.append(skill)
    save_json(SKILLS_PATH, skills)
    return skill


@app.get("/api/tasks")
def list_tasks() -> List[Dict[str, Any]]:
    ensure_data_files()
    return load_json(TASKS_PATH)


@app.post("/api/tasks")
def create_task(payload: TaskCreate) -> Dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    task = {
        "id": f"task-{len(tasks) + 1}",
        "title": payload.title,
        "description": payload.description,
        "status": payload.status,
        "source_url": payload.source_url,
        "capability": payload.capability,
    }
    tasks.append(task)
    save_json(TASKS_PATH, tasks)
    return task


@app.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: str) -> Dict[str, Any]:
    tasks = load_json(TASKS_PATH)
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = "approved"
            save_json(TASKS_PATH, tasks)
            return task
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


@app.post("/api/grow")
def propose_growth(idea: Dict[str, str]) -> Dict[str, Any]:
    title = idea.get("title") or "New capability idea"
    description = idea.get("description") or "A candidate capability to learn from GitHub sources."
    source_url = idea.get("source_url") or "https://github.com"
    current = load_json(TASKS_PATH)
    new_task = {
        "id": f"task-{len(current) + 1}",
        "title": title,
        "description": description,
        "status": "proposed",
        "source_url": source_url,
        "capability": "growth_candidate",
    }
    current.append(new_task)
    save_json(TASKS_PATH, current)
    return new_task


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
