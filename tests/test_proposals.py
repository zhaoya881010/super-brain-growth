from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as application


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(application, "BASE_DIR", tmp_path)
    monkeypatch.setattr(application, "DATA_DIR", data_dir)
    monkeypatch.setattr(application, "SKILLS_PATH", data_dir / "skills.json")
    monkeypatch.setattr(application, "TASKS_PATH", data_dir / "tasks.json")
    monkeypatch.setattr(application, "REPOS_PATH", data_dir / "repos.json")
    monkeypatch.setattr(application, "PROPOSALS_PATH", data_dir / "proposals.json")
    monkeypatch.setattr(application, "SANDBOX_ROOT", tmp_path / "sandbox" / "worktrees")
    return TestClient(application.app)


def create_task(client, **extra):
    return client.post(
        "/api/tasks",
        json={
            "title": "Review parser changes",
            "description": "Review a safe parser improvement proposal.",
            **extra,
        },
    )


def submit_proposal(client, task_id, files):
    return client.post(f"/api/tasks/{task_id}/proposals", json={"files": files})


def test_task_verification_and_status_are_managed(client):
    response = create_task(client, verification=["Accept valid input"])
    assert response.status_code == 200
    task = response.json()
    step = task["verification"][0]
    assert step["status"] == "pending"

    updated = client.patch(
        f"/api/tasks/{task['id']}/verification/{step['id']}", json={"status": "passed"}
    )
    assert updated.json()["verification"][0]["status"] == "passed"
    assert client.patch(
        f"/api/tasks/{task['id']}/status", json={"status": "in_progress"}
    ).json()["status"] == "in_progress"


def test_valid_proposal_is_isolated_and_reviewable(client, tmp_path):
    task = create_task(client).json()
    original = "def current():\n    return 1\n"
    (tmp_path / "parser.py").write_text(original, encoding="utf-8")

    response = submit_proposal(
        client, task["id"], [{"path": "parser.py", "content": "def current():\n    return 2\n"}]
    )
    assert response.status_code == 201
    proposal = response.json()
    assert proposal["validation_status"] == "passed"
    assert proposal["static_checks"][0]["passed"] is True
    assert "return 1" in proposal["diff"] and "return 2" in proposal["diff"]
    assert proposal["summary"]["modified_files"] == 1
    assert (tmp_path / "parser.py").read_text(encoding="utf-8") == original
    stored_path = tmp_path / proposal["sandbox_path"] / "parser.py"
    assert stored_path.read_text(encoding="utf-8") == "def current():\n    return 2\n"

    fetched = client.get(f"/api/tasks/{task['id']}/proposals/{proposal['id']}")
    assert fetched.json()["id"] == proposal["id"]
    listed = client.get(f"/api/tasks/{task['id']}/proposals")
    assert [item["id"] for item in listed.json()] == [proposal["id"]]
    approved = client.post(
        f"/api/tasks/{task['id']}/proposals/{proposal['id']}/approve",
        json={"reason": "Reviewed manually"},
    )
    assert approved.json()["review_status"] == "approved"
    assert "no merge" in approved.json()["decision"]["effect"].lower()


def test_static_validation_failure_is_recorded_but_cannot_be_approved(client):
    task = create_task(client).json()
    response = submit_proposal(
        client,
        task["id"],
        [
            {"path": "broken.py", "content": "def broken(:\n    pass\n"},
            {"path": "broken.json", "content": '{"key": }'},
        ],
    )
    assert response.status_code == 201
    proposal = response.json()
    assert proposal["validation_status"] == "failed"
    assert all(not check["passed"] for check in proposal["static_checks"])
    approval = client.post(f"/api/tasks/{task['id']}/proposals/{proposal['id']}/approve")
    assert approval.status_code == 409


@pytest.mark.parametrize(
    "path, expected_status",
    [
        ("../escape.py", 422),
        ("data/secret.json", 422),
        ("notes.txt", 422),
    ],
)
def test_unsafe_proposal_paths_are_rejected(client, path, expected_status):
    task = create_task(client).json()
    response = submit_proposal(client, task["id"], [{"path": path, "content": "{}"}])
    assert response.status_code == expected_status


def test_duplicate_paths_are_rejected_case_insensitively(client):
    task = create_task(client).json()
    response = submit_proposal(
        client,
        task["id"],
        [{"path": "src.py", "content": "pass\n"}, {"path": "SRC.PY", "content": "pass\n"}],
    )
    assert response.status_code == 422


def test_oversized_file_is_rejected(client):
    task = create_task(client).json()
    response = submit_proposal(
        client,
        task["id"],
        [{"path": "large.json", "content": " " * (application.MAX_PROPOSAL_FILE_BYTES + 1)}],
    )
    assert response.status_code == 413


def test_symlink_proposal_path_is_rejected(client, tmp_path, monkeypatch):
    link = tmp_path / "alias.py"
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == link or original_is_symlink(path),
    )

    task = create_task(client).json()
    response = submit_proposal(client, task["id"], [{"path": "alias.py", "content": "pass\n"}])
    assert response.status_code == 422


def test_rejection_decision_is_recorded(client):
    task = create_task(client).json()
    proposal = submit_proposal(client, task["id"], [{"path": "new.json", "content": "{}"}]).json()
    response = client.post(
        f"/api/tasks/{task['id']}/proposals/{proposal['id']}/reject",
        json={"reason": "Needs revision"},
    )
    assert response.json()["review_status"] == "rejected"
    assert response.json()["decision"]["reason"] == "Needs revision"


def test_existing_skill_repo_and_readme_analysis_apis_remain_available(client, monkeypatch):
    skill = client.post(
        "/api/skills",
        json={
            "name": "Parser patterns",
            "description": "Reusable parsing patterns for structured input.",
            "source_url": "https://example.com/parser",
        },
    )
    assert skill.status_code == 200
    assert client.get("/api/skills").json()[0]["id"] == skill.json()["id"]

    repo = client.post(
        "/api/repos",
        json={"url": "https://github.com/example/project", "purpose": "Read its README"},
    )
    assert repo.status_code == 201
    monkeypatch.setattr(
        application,
        "analyze_github_repo",
        lambda owner, name: {
            "full_name": f"{owner}/{name}",
            "readme_excerpt": "README content",
        },
    )
    analyzed = client.post(f"/api/repos/{repo.json()['id']}/analyze")
    assert analyzed.json()["readme_excerpt"] == "README content"
    assert client.get("/api/repos").json()[0]["status"] == "analyzed"

    improvement = client.post(
        f"/api/repos/{repo.json()['id']}/improvements",
        json={"title": "Extract a pattern", "description": "Create a reviewable improvement task."},
    )
    assert improvement.status_code == 201
    assert improvement.json()["source_url"] == repo.json()["url"]
