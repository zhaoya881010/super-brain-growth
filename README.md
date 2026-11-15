# Super Brain Growth MVP

This project is a minimal self-growing AI brain starter. It is made to be intentionally safe and reviewable.

## What it does

- Tracks skills that are available to the system
- Tracks growth tasks and approval status
- Exposes a minimal REST API for adding skills and tasks
- Stores candidate growth ideas sourced from GitHub/knowledge projects
- Provides a very small dashboard to view system state

## Architecture

- `app.py`: FastAPI app and REST endpoints
- `data/skills.json`: verified or proposed skills
- `data/tasks.json`: growth tasks and work in progress
- `requirements.txt`: app dependencies

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Then open:

- http://localhost:8000/
- http://localhost:8000/docs

## Example requests

```bash
curl http://localhost:8000/api/skills
curl -X POST http://localhost:8000/api/skills \
  -H "Content-Type: application/json" \
  -d '{
    "name": "repo-researcher",
    "description": "Find relevant GitHub repositories and summarize their fit for a task.",
    "source_url": "https://github.com/search?q=github+repo+search",
    "status": "proposed",
    "tags": ["github", "research"]
  }'
```

## Growth model

The system is designed to encourage a safe growth loop:

1. Observe a gap or idea.
2. Turn it into a growth task.
3. Gather source links and candidate project references.
4. Validate the skill or capability in a controlled way.
5. Approve only after review.
6. Preserve a trail of changes and decisions.

## Future extensions

- Add a real UI with cards and filters.
- Add an approval workflow with GitHub PRs.
- Integrate with GitHub API for repo discovery.
- Expand to real memory, tool adapters, and skills engine.
