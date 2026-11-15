# Super Brain Growth

A small, reviewable starter for a system that can learn from open-source projects and grow through tested, human-reviewed changes.

## What it does

- Tracks skills that are available to the system.
- Tracks growth tasks and approval status.
- Lets you register public GitHub repos by URL.
- Fetches public metadata + README excerpt for those repos.
- Converts promising repo observations into reviewable improvement tasks.
- Keeps a clear safety boundary: it does not clone, execute, or modify upstream source code.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open:
- http://127.0.0.1:8000/
- http://127.0.0.1:8000/docs

## Example: register a public GitHub repo

```bash
curl -X POST http://127.0.0.1:8000/api/repos \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/langchain-ai/langgraph","purpose":"Study agent workflow patterns"}'
```

## Safety model

This version intentionally does not clone or execute code from third-party repos. It only reads public metadata and README content through the GitHub API. Improvement tasks remain proposals until you review and implement them in your own branch.

## Structure

- `app.py`: API and UI entrypoint
- `data/skills.json`: candidate skills
- `data/tasks.json`: growth tasks
- `data/repos.json`: registered GitHub sources

## Next stage

The next safe step is to add a sandboxed agent that can propose code changes to this project itself, run tests in isolation, and create a PR for review. It should never execute untrusted third-party code without approval and a sandbox boundary.

