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
    """Sample workout plan for testing (block-based format)."""
    return {
        "day_name": "Test Workout",
        "location": "Home",
        "phase": "Foundation",
        "blocks": [
            {
                "block_type": "warmup",
                "title": "Warmup",
                "exercises": [
                    {
                        "id": "warmup_0",
                        "name": "Stability Start",
                        "type": "checklist",
                        "items": ["Cat-Cow x10", "Bird-Dog x5/side"]
                    }
                ]
            },
            {
                "block_type": "strength",
                "title": "Strength",
                "rest_guidance": "Rest 2 min",
                "exercises": [
                    {
                        "id": "ex_1",
                        "name": "KB Goblet Squat",
                        "type": "strength",
                        "target_sets": 3,
                        "target_reps": "10",
                        "guidance_note": "Tempo 3-1-1"
                    }
                ]
            },
            {
                "block_type": "cardio",
                "title": "Conditioning",
                "exercises": [
                    {
                        "id": "cardio_1",
                        "name": "Zone 2 Bike",
                        "type": "duration",
                        "target_duration_min": 15,
                        "guidance_note": "HR 135-148"
                    }
                ]
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
        "warmup_0": {
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

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Insert today's plan into relational tables
    cursor.execute("""
        INSERT INTO workout_sessions
        (date, day_name, location, phase, last_modified, modified_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (today, "Test Workout", "Home", "Foundation", now, "test"))
    s1 = cursor.lastrowid

    # Warmup block
    cursor.execute("""
        INSERT INTO session_blocks (session_id, position, block_type, title)
        VALUES (?, ?, ?, ?)
    """, (s1, 0, "warmup", "Warmup"))
    b1 = cursor.lastrowid

    cursor.execute("""
        INSERT INTO planned_exercises
        (session_id, block_id, exercise_key, position, name, exercise_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (s1, b1, "warmup_0", 0, "Stability Start", "checklist"))
    e_warmup = cursor.lastrowid

    for i, item in enumerate(["Cat-Cow x10", "Bird-Dog x5/side"]):
        cursor.execute(
            "INSERT INTO checklist_items (exercise_id, position, item_text) VALUES (?, ?, ?)",
            (e_warmup, i, item)
        )

    # Strength block
    cursor.execute("""
        INSERT INTO session_blocks (session_id, position, block_type, title, rest_guidance)
        VALUES (?, ?, ?, ?, ?)
    """, (s1, 1, "strength", "Strength", "Rest 2 min"))
    b2 = cursor.lastrowid

    cursor.execute("""
        INSERT INTO planned_exercises
        (session_id, block_id, exercise_key, position, name, exercise_type,
         target_sets, target_reps, guidance_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (s1, b2, "ex_1", 0, "KB Goblet Squat", "strength", 3, "10", "Tempo 3-1-1"))

    # Cardio block
    cursor.execute("""
        INSERT INTO session_blocks (session_id, position, block_type, title)
        VALUES (?, ?, ?, ?)
    """, (s1, 2, "cardio", "Conditioning"))
    b3 = cursor.lastrowid

    cursor.execute("""
        INSERT INTO planned_exercises
        (session_id, block_id, exercise_key, position, name, exercise_type,
         target_duration_min, guidance_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (s1, b3, "cardio_1", 0, "Zone 2 Bike", "duration", 15, "HR 135-148"))

    # Yesterday's plan
    cursor.execute("""
        INSERT INTO workout_sessions
        (date, day_name, location, phase, last_modified, modified_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (yesterday, "Yesterday's Workout", "Home", "Foundation", now, "test"))
    s2 = cursor.lastrowid

    cursor.execute("""
        INSERT INTO session_blocks (session_id, position, block_type, title)
        VALUES (?, ?, ?, ?)
    """, (s2, 0, "strength", "Strength"))
    b_y = cursor.lastrowid

    cursor.execute("""
        INSERT INTO planned_exercises
        (session_id, block_id, exercise_key, position, name, exercise_type,
         target_sets, target_reps)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (s2, b_y, "ex_1", 0, "Squat", "strength", 3, "10"))

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
    import server

    # Use init_database to create all tables with new schema
    server.init_database(db_path=temp_db_path)

    return MCPConfig(db_path=temp_db_path, max_rows=100)


@pytest.fixture
def db_manager(mcp_config):
    """Create DatabaseManager for testing."""
    from coach_mcp.server import DatabaseManager
    return DatabaseManager(mcp_config)
