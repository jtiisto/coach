"""Pytest configuration and fixtures for Coach tests."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="function")
def temp_db_path():
    """Create a temporary database file for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield Path(db_path)
    # Cleanup after test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(scope="function")
def test_app(temp_db_path, tmp_path, monkeypatch):
    """
    Create a test FastAPI app with isolated database.
    Uses monkeypatch to override DATABASE_PATH and PUBLIC_DIR.
    """
    # Create minimal public directory structure for static file tests
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    (public_dir / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="/styles.css">'
        '<script src="/js/app.js"></script></head><body>Test</body></html>'
    )
    (public_dir / "styles.css").write_text("body { margin: 0; }")
    js_dir = public_dir / "js"
    js_dir.mkdir()
    (js_dir / "app.js").write_text("console.log('test');")

    # Patch the module-level variables
    import server
    monkeypatch.setattr(server, "DATABASE_PATH", temp_db_path)
    monkeypatch.setattr(server, "PUBLIC_DIR", public_dir)

    # Initialize database with new path
    server.init_database()

    yield server.app


@pytest.fixture(scope="function")
def client(test_app):
    """Create a test client for the FastAPI app."""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def sample_plan():
    """Sample workout plan for testing."""
    return {
        "day_name": "Test Workout",
        "location": "Home",
        "phase": "Foundation",
        "exercises": [
            {
                "id": "warmup_1",
                "name": "Stability Start",
                "type": "checklist",
                "items": ["Cat-Cow x10", "Bird-Dog x5/side"]
            },
            {
                "id": "ex_1",
                "name": "KB Goblet Squat",
                "type": "strength",
                "target_sets": 3,
                "target_reps": "10",
                "guidance_note": "Tempo 3-1-1"
            },
            {
                "id": "cardio_1",
                "name": "Zone 2 Bike",
                "type": "duration",
                "target_duration_min": 15,
                "guidance_note": "HR 135-148"
            }
        ]
    }


@pytest.fixture
def sample_log():
    """Sample workout log for testing."""
    return {
        "session_feedback": {
            "pain_discomfort": "None",
            "general_notes": "Good session"
        },
        "warmup_1": {
            "completed_items": ["Cat-Cow x10", "Bird-Dog x5/side"]
        },
        "ex_1": {
            "completed": True,
            "user_note": "Felt strong",
            "sets": [
                {"set_num": 1, "weight": 24, "reps": 10, "rpe": 7},
                {"set_num": 2, "weight": 24, "reps": 10, "rpe": 7.5},
                {"set_num": 3, "weight": 24, "reps": 10, "rpe": 8}
            ]
        },
        "cardio_1": {
            "completed": True,
            "duration_min": 16,
            "avg_hr": 142,
            "max_hr": 149
        }
    }


@pytest.fixture
def registered_client(client):
    """A client that has been registered with the server."""
    client_id = "test-client-001"
    response = client.post(f"/api/workout/register?client_id={client_id}&client_name=TestClient")
    assert response.status_code == 200
    return client_id


@pytest.fixture
def seeded_database(client, registered_client, sample_plan, sample_log, temp_db_path):
    """Database seeded with sample plan and log data for testing."""
    import sqlite3

    # Insert plan directly into database (simulating MCP)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    # Insert plans
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cursor.execute(
        "INSERT INTO workout_plans (date, plan_json, last_modified, last_modified_by) VALUES (?, ?, ?, ?)",
        (today, json.dumps(sample_plan), now, "test")
    )
    cursor.execute(
        "INSERT INTO workout_plans (date, plan_json, last_modified, last_modified_by) VALUES (?, ?, ?, ?)",
        (yesterday, json.dumps({**sample_plan, "day_name": "Yesterday's Workout"}), now, "test")
    )
    conn.commit()
    conn.close()

    # Upload log via API
    client.post(
        "/api/workout/sync",
        json={
            "clientId": registered_client,
            "logs": {today: sample_log}
        }
    )

    return {
        "client_id": registered_client,
        "plan": sample_plan,
        "log": sample_log,
        "dates": [today, yesterday]
    }


# ==================== MCP Fixtures ====================

@pytest.fixture
def mcp_config(temp_db_path):
    """Create MCP config for testing."""
    from coach_mcp.config import MCPConfig

    # Initialize the database first
    import server
    import sqlite3

    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_plans (
            date TEXT PRIMARY KEY,
            plan_json TEXT NOT NULL,
            last_modified TEXT NOT NULL,
            last_modified_by TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_logs (
            date TEXT PRIMARY KEY,
            log_json TEXT NOT NULL,
            last_modified TEXT NOT NULL,
            last_modified_by TEXT
        )
    """)
    conn.commit()
    conn.close()

    return MCPConfig(db_path=temp_db_path, max_rows=100)


@pytest.fixture
def db_manager(mcp_config):
    """Create DatabaseManager for testing."""
    from coach_mcp.server import DatabaseManager
    return DatabaseManager(mcp_config)
