# Super Brain Growth

A small, reviewable starter for a system that can learn from open-source projects and grow through tested, human-reviewed changes.

## What it does

- Tracks skills that are available to the system.
- Tracks growth tasks, verification steps, and status.
- Lets you register public GitHub repos by URL.
- Fetches public metadata + README excerpt for those repos.
- Converts promising repo observations into reviewable improvement tasks.
- Stores code proposals in task-specific sandbox directories without changing project files.
- Keeps a clear safety boundary: proposal code is never executed, tested, merged, or deployed.

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

## Tasks and code proposals

Tasks may include verification acceptance steps. Each step starts with `pending` and can be
updated to `in_progress`, `passed`, or `failed`; task status can be updated separately.

```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Improve parsing","description":"Handle malformed input safely.","verification":["Valid JSON is accepted","Invalid JSON is rejected"]}'
```

Submit a proposal with relative paths and file contents:

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/<task_id>/proposals \
  -H 'Content-Type: application/json' \
  -d '{"files":[{"path":"parser.py","content":"def parse(value):\n    return value\n"}]}'
```

Each proposal is written under `sandbox/worktrees/<task_id>/<proposal_id>/`. Only `.py` and
`.json` files are accepted (1 MB per file, 5 MB per proposal). Paths cannot traverse directories,
follow symlinks, or target protected directories. Python is checked with syntax compilation and
JSON is parsed; these checks do not execute proposal content. The response includes static check
results, a unified diff, and a summary. Read or list review results using
`GET /api/tasks/<task_id>/proposals` and
`GET /api/tasks/<task_id>/proposals/<proposal_id>`.

Human reviewers can record a decision with
`POST /api/tasks/<task_id>/proposals/<proposal_id>/approve` or `/reject`, optionally sending
`{"reason":"..."}`. A proposal that fails static validation cannot be approved. Approval only
records the decision; it does not merge or deploy changes.

## Run tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Example: register a public GitHub repo

```bash
curl -X POST http://127.0.0.1:8000/api/repos \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/langchain-ai/langgraph","purpose":"Study agent workflow patterns"}'
```

## Safety model

This version does not clone or execute code from third-party repos. It only reads public metadata and README content through the GitHub API. Submitted proposals are stored separately from project files; validation is limited to Python syntax compilation and JSON parsing, and reviewer approval never applies the proposed changes.

## Structure

- `app.py`: API and UI entrypoint
- `data/skills.json`: candidate skills
- `data/tasks.json`: growth tasks
- `data/repos.json`: registered GitHub sources
- `data/proposals.json`: proposal review records
- `sandbox/worktrees/<task_id>/`: isolated proposal files (git-ignored)

## Next stage

Proposals remain review artifacts only. Applying changes, running proposal tests, merging, and deployment are intentionally outside this review workflow.

