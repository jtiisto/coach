"""
Coach Exercise Tracker Server - FastAPI backend with SQLite
Workout plan management and log synchronization
"""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel


# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
PUBLIC_DIR = PROJECT_ROOT / "public"

# Cache busting: unique version generated on each server start
SERVER_VERSION = uuid.uuid4().hex[:8]


def is_test_mode() -> bool:
    """Check if running in test mode via environment variable."""
    import os
    return os.environ.get("COACH_TEST_MODE", "").lower() == "true"


def is_pytest_running() -> bool:
    """Check if running under pytest (tests control their own data)."""
    import sys
    return "pytest" in sys.modules


def get_database_path() -> Path:
    """Get the database path based on mode."""
    if is_test_mode():
        return PROJECT_ROOT / "coach_test.db"
    return PROJECT_ROOT / "coach.db"


# Module-level DATABASE_PATH for backwards compatibility with tests
DATABASE_PATH = get_database_path()


@asynccontextmanager
async def lifespan(app):
    # Startup - recalculate database path only if running in test mode
    # (test fixtures patch DATABASE_PATH directly, so we don't override in that case)
    global DATABASE_PATH
    if is_test_mode() and not is_pytest_running():
        # Only seed when running server manually with --test flag
        # pytest controls its own test data via fixtures
        DATABASE_PATH = get_database_path()
        init_database()
        seed_test_data()
    elif not is_pytest_running():
        init_database()
    yield
    # Shutdown (nothing needed)


app = FastAPI(title="Coach Exercise Tracker Server", lifespan=lifespan)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Database helpers
@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_database(db_path=None):
    """Initialize the database with required tables.

    Args:
        db_path: Optional path override. If None, uses DATABASE_PATH.
    """
    path = str(db_path) if db_path else str(DATABASE_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    # workout_sessions - one row per scheduled workout day
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_sessions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT NOT NULL UNIQUE,
            day_name      TEXT NOT NULL,
            location      TEXT,
            phase         TEXT,
            duration_min  INTEGER,
            last_modified TEXT NOT NULL,
            modified_by   TEXT,
            extra         TEXT
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_date ON workout_sessions(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_modified ON workout_sessions(last_modified)")

    # session_blocks - block groupings within a session
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_blocks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
            position       INTEGER NOT NULL,
            block_type     TEXT NOT NULL,
            title          TEXT,
            duration_min   INTEGER,
            rest_guidance  TEXT,
            rounds         INTEGER,
            UNIQUE(session_id, position)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_blocks_session ON session_blocks(session_id)")

    # planned_exercises - individual exercises, directly queryable
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS planned_exercises (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
            block_id        INTEGER NOT NULL REFERENCES session_blocks(id) ON DELETE CASCADE,
            exercise_key    TEXT NOT NULL,
            position        INTEGER NOT NULL,
            name            TEXT NOT NULL,
            exercise_type   TEXT NOT NULL,
            target_sets     INTEGER,
            target_reps     TEXT,
            target_duration_min INTEGER,
            target_duration_sec INTEGER,
            rounds          INTEGER,
            work_duration_sec   INTEGER,
            rest_duration_sec   INTEGER,
            guidance_note   TEXT,
            hide_weight     INTEGER DEFAULT 0,
            show_time       INTEGER DEFAULT 0,
            extra           TEXT,
            UNIQUE(session_id, exercise_key)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exercises_session ON planned_exercises(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exercises_name ON planned_exercises(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exercises_type ON planned_exercises(exercise_type)")

    # checklist_items - normalized checklist items for warmup/checklist exercises
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_id     INTEGER NOT NULL REFERENCES planned_exercises(id) ON DELETE CASCADE,
            position        INTEGER NOT NULL,
            item_text       TEXT NOT NULL,
            UNIQUE(exercise_id, position)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checklist_items_exercise ON checklist_items(exercise_id)")

    # workout_session_logs - session-level log data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_session_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER REFERENCES workout_sessions(id),
            date            TEXT NOT NULL UNIQUE,
            pain_discomfort TEXT,
            general_notes   TEXT,
            last_modified   TEXT NOT NULL,
            modified_by     TEXT,
            extra           TEXT
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_session_logs_date ON workout_session_logs(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_logs_modified ON workout_session_logs(last_modified)")

    # exercise_logs - per-exercise completion data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exercise_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_log_id  INTEGER NOT NULL REFERENCES workout_session_logs(id) ON DELETE CASCADE,
            exercise_id     INTEGER REFERENCES planned_exercises(id),
            exercise_key    TEXT NOT NULL,
            completed       INTEGER DEFAULT 0,
            user_note       TEXT,
            duration_min    REAL,
            avg_hr          INTEGER,
            max_hr          INTEGER,
            extra           TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exercise_logs_session ON exercise_logs(session_log_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exercise_logs_exercise ON exercise_logs(exercise_id)")

    # checklist_log_items - completed checklist items
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checklist_log_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_log_id INTEGER NOT NULL REFERENCES exercise_logs(id) ON DELETE CASCADE,
            item_text       TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checklist_log_items_exercise ON checklist_log_items(exercise_log_id)")

    # set_logs - individual set data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS set_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_log_id INTEGER NOT NULL REFERENCES exercise_logs(id) ON DELETE CASCADE,
            set_num         INTEGER NOT NULL,
            weight          REAL,
            reps            INTEGER,
            rpe             REAL,
            unit            TEXT DEFAULT 'lbs',
            duration_sec    REAL,
            completed       INTEGER DEFAULT 0,
            extra           TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_set_logs_exercise ON set_logs(exercise_log_id)")

    # clients table - track connected clients (unchanged)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT,
            last_seen_at TEXT
        )
    """)

    # meta_sync table (unchanged)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta_sync (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ==================== Plan/Log Assembly Helpers ====================


def _assemble_plan(conn, session_row):
    """Assemble plan dict from relational tables for sync response."""
    cursor = conn.cursor()
    session_id = session_row["id"]

    cursor.execute("""
        SELECT * FROM session_blocks WHERE session_id = ? ORDER BY position
    """, (session_id,))
    block_rows = cursor.fetchall()

    blocks = []
    for br in block_rows:
        cursor.execute("""
            SELECT * FROM planned_exercises WHERE block_id = ? ORDER BY position
        """, (br["id"],))
        ex_rows = cursor.fetchall()

        exercises = []
        for er in ex_rows:
            exercise = {
                "id": er["exercise_key"],
                "name": er["name"],
                "type": er["exercise_type"],
            }
            if er["target_sets"] is not None:
                exercise["target_sets"] = er["target_sets"]
            if er["target_reps"] is not None:
                exercise["target_reps"] = er["target_reps"]
            if er["target_duration_min"] is not None:
                exercise["target_duration_min"] = er["target_duration_min"]
            if er["target_duration_sec"] is not None:
                exercise["target_duration_sec"] = er["target_duration_sec"]
            if er["rounds"] is not None:
                exercise["rounds"] = er["rounds"]
            if er["work_duration_sec"] is not None:
                exercise["work_duration_sec"] = er["work_duration_sec"]
            if er["rest_duration_sec"] is not None:
                exercise["rest_duration_sec"] = er["rest_duration_sec"]
            if er["guidance_note"]:
                exercise["guidance_note"] = er["guidance_note"]
            if er["hide_weight"]:
                exercise["hide_weight"] = True
            if er["show_time"]:
                exercise["show_time"] = True

            if er["exercise_type"] == "checklist":
                cursor.execute("""
                    SELECT item_text FROM checklist_items
                    WHERE exercise_id = ? ORDER BY position
                """, (er["id"],))
                exercise["items"] = [r["item_text"] for r in cursor.fetchall()]

            exercises.append(exercise)

        blocks.append({
            "block_index": br["position"],
            "block_type": br["block_type"],
            "title": br["title"],
            "duration_min": br["duration_min"],
            "rest_guidance": br["rest_guidance"] or "",
            "rounds": br["rounds"],
            "exercises": exercises,
        })

    return {
        "day_name": session_row["day_name"],
        "location": session_row["location"],
        "phase": session_row["phase"],
        "total_duration_min": session_row["duration_min"],
        "blocks": blocks,
    }


def _assemble_log(conn, log_row):
    """Assemble log dict from relational tables for sync response."""
    cursor = conn.cursor()
    log = {}

    # Session feedback
    feedback = {}
    if log_row["pain_discomfort"]:
        feedback["pain_discomfort"] = log_row["pain_discomfort"]
    if log_row["general_notes"]:
        feedback["general_notes"] = log_row["general_notes"]
    log["session_feedback"] = feedback

    # Exercise logs
    cursor.execute("""
        SELECT * FROM exercise_logs WHERE session_log_id = ?
    """, (log_row["id"],))

    for el in cursor.fetchall():
        entry = {}
        if el["completed"]:
            entry["completed"] = True
        if el["user_note"]:
            entry["user_note"] = el["user_note"]
        if el["duration_min"] is not None:
            entry["duration_min"] = el["duration_min"]
        if el["avg_hr"] is not None:
            entry["avg_hr"] = el["avg_hr"]
        if el["max_hr"] is not None:
            entry["max_hr"] = el["max_hr"]

        # Sets
        cursor.execute("""
            SELECT * FROM set_logs WHERE exercise_log_id = ? ORDER BY set_num
        """, (el["id"],))
        sets = cursor.fetchall()
        if sets:
            entry["sets"] = []
            for s in sets:
                set_dict = {"set_num": s["set_num"]}
                if s["weight"] is not None:
                    set_dict["weight"] = s["weight"]
                if s["reps"] is not None:
                    set_dict["reps"] = s["reps"]
                if s["rpe"] is not None:
                    set_dict["rpe"] = s["rpe"]
                if s["unit"]:
                    set_dict["unit"] = s["unit"]
                if s["duration_sec"] is not None:
                    set_dict["duration_sec"] = s["duration_sec"]
                if s["completed"]:
                    set_dict["completed"] = True
                entry["sets"].append(set_dict)

        # Checklist items
        cursor.execute("""
            SELECT item_text FROM checklist_log_items WHERE exercise_log_id = ?
        """, (el["id"],))
        items = cursor.fetchall()
        if items:
            entry["completed_items"] = [r["item_text"] for r in items]

        log[el["exercise_key"]] = entry

    return log


def _store_log(conn, date_str, log_data, client_id, now):
    """Decompose a log dict into relational tables."""
    cursor = conn.cursor()

    # Extract session feedback
    feedback = log_data.get("session_feedback", {})
    pain = feedback.get("pain_discomfort")
    notes = feedback.get("general_notes")

    # Find session for this date
    cursor.execute("SELECT id FROM workout_sessions WHERE date = ?", (date_str,))
    session_row = cursor.fetchone()
    session_id = session_row["id"] if session_row else None

    # Delete existing log for this date (CASCADE cleans exercise_logs, set_logs, etc.)
    cursor.execute("DELETE FROM workout_session_logs WHERE date = ?", (date_str,))

    # Insert session log
    cursor.execute("""
        INSERT INTO workout_session_logs
        (session_id, date, pain_discomfort, general_notes, last_modified, modified_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, date_str, pain, notes, now, client_id))
    session_log_id = cursor.lastrowid

    # Process exercise entries
    meta_keys = {"session_feedback", "_lastModifiedAt", "_lastModifiedBy"}
    for exercise_key, exercise_data in log_data.items():
        if exercise_key in meta_keys:
            continue
        if not isinstance(exercise_data, dict):
            continue

        # Find planned_exercises.id for this exercise_key
        exercise_id = None
        if session_id:
            cursor.execute("""
                SELECT id FROM planned_exercises
                WHERE session_id = ? AND exercise_key = ?
            """, (session_id, exercise_key))
            ex_row = cursor.fetchone()
            if ex_row:
                exercise_id = ex_row["id"]

        # Insert exercise log
        cursor.execute("""
            INSERT INTO exercise_logs
            (session_log_id, exercise_id, exercise_key, completed, user_note,
             duration_min, avg_hr, max_hr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_log_id, exercise_id, exercise_key,
            1 if exercise_data.get("completed") else 0,
            exercise_data.get("user_note"),
            exercise_data.get("duration_min"),
            exercise_data.get("avg_hr"),
            exercise_data.get("max_hr"),
        ))
        exercise_log_id = cursor.lastrowid

        # Store sets
        for s in exercise_data.get("sets", []):
            cursor.execute("""
                INSERT INTO set_logs
                (exercise_log_id, set_num, weight, reps, rpe, unit, duration_sec, completed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exercise_log_id, s.get("set_num", 0),
                s.get("weight"), s.get("reps"), s.get("rpe"),
                s.get("unit", "lbs"), s.get("duration_sec"),
                1 if s.get("completed") else 0,
            ))

        # Store checklist items
        for item in exercise_data.get("completed_items", []):
            cursor.execute("""
                INSERT INTO checklist_log_items (exercise_log_id, item_text)
                VALUES (?, ?)
            """, (exercise_log_id, item))


# Pydantic models
class WorkoutSyncPayload(BaseModel):
    clientId: str
    logs: dict[str, Any] = {}  # date -> log_json

class WorkoutSyncResponse(BaseModel):
    plans: dict[str, Any]  # date -> plan
    logs: dict[str, Any]   # date -> log
    serverTime: str

class StatusResponse(BaseModel):
    lastModified: Optional[str] = None


# API Endpoints
@app.get("/api/workout/status", response_model=StatusResponse)
def workout_status():
    """Get the last server sync time."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM meta_sync WHERE key = 'last_server_sync_time'")
        row = cursor.fetchone()

        if row:
            return StatusResponse(lastModified=row["value"])
        return StatusResponse(lastModified=None)


@app.post("/api/workout/register")
def register_client(client_id: str, client_name: Optional[str] = None):
    """Register or update a client."""
    with get_db() as conn:
        cursor = conn.cursor()
        now = get_utc_now()
        cursor.execute("""
            INSERT OR REPLACE INTO clients (id, name, last_seen_at)
            VALUES (?, ?, ?)
        """, (client_id, client_name or f"Client-{client_id[:8]}", now))
        conn.commit()
        return {"status": "ok", "clientId": client_id}


@app.get("/api/workout/sync", response_model=WorkoutSyncResponse)
def workout_sync_get(
    client_id: str = Query(...),
    last_sync_time: Optional[str] = Query(None)
):
    """
    Fetch workout plans and logs.
    If last_sync_time is provided, returns only changes since that time.
    Otherwise returns all data.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Update client last seen
        now = get_utc_now()
        cursor.execute("""
            UPDATE clients SET last_seen_at = ? WHERE id = ?
        """, (now, client_id))

        # Fetch plans from workout_sessions
        if last_sync_time:
            cursor.execute("""
                SELECT * FROM workout_sessions
                WHERE last_modified > ?
                ORDER BY date
            """, (last_sync_time,))
        else:
            cursor.execute("SELECT * FROM workout_sessions ORDER BY date")

        session_rows = cursor.fetchall()
        plans = {}
        for row in session_rows:
            plan = _assemble_plan(conn, row)
            plan["_lastModified"] = row["last_modified"]
            plans[row["date"]] = plan

        # Fetch logs from workout_session_logs
        if last_sync_time:
            cursor.execute("""
                SELECT * FROM workout_session_logs
                WHERE last_modified > ?
                ORDER BY date
            """, (last_sync_time,))
        else:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT * FROM workout_session_logs
                WHERE date >= ?
                ORDER BY date
            """, (thirty_days_ago,))

        log_rows = cursor.fetchall()
        logs = {}
        for row in log_rows:
            log = _assemble_log(conn, row)
            log["_lastModified"] = row["last_modified"]
            logs[row["date"]] = log

        conn.commit()
        return WorkoutSyncResponse(plans=plans, logs=logs, serverTime=now)


@app.post("/api/workout/sync")
def workout_sync_post(payload: WorkoutSyncPayload):
    """
    Upload workout logs from client.
    Uses last-write-wins strategy (no conflict detection).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        now = get_utc_now()
        client_id = payload.clientId

        # Update client last seen
        cursor.execute("""
            INSERT OR REPLACE INTO clients (id, name, last_seen_at)
            VALUES (?, ?, ?)
        """, (client_id, f"Client-{client_id[:8]}", now))

        applied_logs = []

        # Process each log
        for date_str, log_data in payload.logs.items():
            _store_log(conn, date_str, log_data, client_id, now)
            applied_logs.append(date_str)

        # Update server sync time
        cursor.execute("""
            INSERT OR REPLACE INTO meta_sync (key, value)
            VALUES ('last_server_sync_time', ?)
        """, (now,))

        conn.commit()

        return {
            "success": True,
            "appliedLogs": applied_logs,
            "serverTime": now
        }


# Static file serving
@app.get("/exercise")
def serve_exercise_app():
    """Serve the main index.html with cache-busting version injected."""
    index_path = PUBLIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")

    # Read and inject version into static file URLs
    html = index_path.read_text()
    html = html.replace('href="/styles.css"', f'href="/styles.css?v={SERVER_VERSION}"')
    html = html.replace('src="/js/app.js"', f'src="/js/app.js?v={SERVER_VERSION}"')

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, must-revalidate"}
    )


@app.get("/styles.css")
def serve_css():
    """Serve the stylesheet with no-cache headers."""
    css_path = PUBLIC_DIR / "styles.css"
    if css_path.exists():
        return FileResponse(
            css_path,
            media_type="text/css",
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail="styles.css not found")


@app.get("/js/{file_path:path}")
def serve_js(file_path: str):
    """Serve JavaScript files with no-cache headers."""
    js_path = PUBLIC_DIR / "js" / file_path
    if js_path.exists() and js_path.is_file():
        return FileResponse(
            js_path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail=f"JS file not found: {file_path}")


@app.get("/manifest.json")
def serve_manifest():
    """Serve the PWA manifest."""
    manifest_path = PUBLIC_DIR / "manifest.json"
    if manifest_path.exists():
        return FileResponse(
            manifest_path,
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail="manifest.json not found")


@app.get("/sw.js")
def serve_service_worker():
    """Serve the service worker from root scope."""
    sw_path = PUBLIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, must-revalidate",
                "Service-Worker-Allowed": "/"
            }
        )
    raise HTTPException(status_code=404, detail="sw.js not found")


@app.get("/icons/{file_path:path}")
def serve_icons(file_path: str):
    """Serve icon files with long cache headers."""
    icon_path = PUBLIC_DIR / "icons" / file_path
    if icon_path.exists() and icon_path.is_file():
        media_type = "image/png"
        if file_path.endswith(".svg"):
            media_type = "image/svg+xml"
        elif file_path.endswith(".ico"):
            media_type = "image/x-icon"
        return FileResponse(
            icon_path,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )
    raise HTTPException(status_code=404, detail=f"Icon not found: {file_path}")


def seed_test_data():
    """Seed the test database with sample workout data for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    now = get_utc_now()

    with get_db() as conn:
        cursor = conn.cursor()

        # --- Today's plan: Lower Body + Conditioning ---
        cursor.execute("""
            INSERT OR REPLACE INTO workout_sessions
            (date, day_name, location, phase, duration_min, last_modified, modified_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (today, "Test Day - Lower Body + Conditioning", "Home", "Foundation", 60, now, "test_seed"))
        s1 = cursor.lastrowid

        # Warmup block
        cursor.execute("""
            INSERT INTO session_blocks (session_id, position, block_type, title)
            VALUES (?, ?, ?, ?)
        """, (s1, 0, "warmup", "Stability Start"))
        b1_warmup = cursor.lastrowid

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (s1, b1_warmup, "warmup_0", 0, "Stability Start", "checklist"))
        e_warmup = cursor.lastrowid

        for i, item in enumerate([
            "Cat-Cow x10", "Bird-Dog x5/side", "Dead Bug x10",
            "Single-Leg Balance 30s/side", "Thoracic Rotations x5/side",
            "Leg Swings x10/direction"
        ]):
            cursor.execute(
                "INSERT INTO checklist_items (exercise_id, position, item_text) VALUES (?, ?, ?)",
                (e_warmup, i, item)
            )

        # Strength block - antagonist pairs with long title + rest guidance
        cursor.execute("""
            INSERT INTO session_blocks
            (session_id, position, block_type, title, rest_guidance)
            VALUES (?, ?, ?, ?, ?)
        """, (s1, 1, "strength",
              "Upper Body Strength (Antagonist Pairs)",
              "60-90 sec after completing each pair. Fallback: if avg HR exceeds 145, switch to straight sets with 90-120 sec rest."))
        b1_strength = cursor.lastrowid

        for key, pos, name, sets, reps, note, hide in [
            ("ex_1", 0, "Push-ups (Pair A)", 3, "To 2 shy of failure",
             "Full ROM, control descent.", 1),
            ("ex_2", 1, "Band Pull-Aparts (Pair A)", 3, "20",
             "Squeeze shoulder blades together.", 1),
            ("ex_3", 2, "DB Floor Press (Pair B)", 3, "8-10",
             "Pause at bottom 1 sec.", 0),
            ("ex_4", 3, "DB Bent-Over Row (Pair B)", 3, "10/side",
             "Pull to hip, squeeze at top.", 0),
            ("ex_5", 4, "Single-Leg Glute Bridge [Light]", 2, "12/leg",
             "Tempo 2-2-1. Squeeze at top 2 sec.", 1),
        ]:
            cursor.execute("""
                INSERT INTO planned_exercises
                (session_id, block_id, exercise_key, position, name, exercise_type,
                 target_sets, target_reps, guidance_note, hide_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s1, b1_strength, key, pos, name, "strength", sets, reps, note, hide))

        # Power block
        cursor.execute("""
            INSERT INTO session_blocks
            (session_id, position, block_type, title, rest_guidance)
            VALUES (?, ?, ?, ?, ?)
        """, (s1, 2, "strength", "Power Block", "90 sec between sets"))
        b1_power = cursor.lastrowid

        for key, pos, name, sets, reps, note, hide in [
            ("pw_1", 0, "KB Swings", 3, "15",
             "Powerful hip snap.", 0),
            ("pw_2", 1, "Farmer's Carry", 2, "45 sec",
             "Heavy, tight core.", 0),
        ]:
            cursor.execute("""
                INSERT INTO planned_exercises
                (session_id, block_id, exercise_key, position, name, exercise_type,
                 target_sets, target_reps, guidance_note, hide_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s1, b1_power, key, pos, name, "strength", sets, reps, note, hide))

        # Cardio block
        cursor.execute("""
            INSERT INTO session_blocks (session_id, position, block_type, title)
            VALUES (?, ?, ?, ?)
        """, (s1, 3, "cardio", "Conditioning"))
        b1_cardio = cursor.lastrowid

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type,
             target_duration_min, guidance_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (s1, b1_cardio, "cardio_1", 0, "Zone 2 Bike", "duration", 15,
              "5 min warm-up (HR <130), then 10 min STRICT Zone 2 (HR 135-148). Target avg: 140-145 bpm."))

        # --- Tomorrow's plan: Heavy Compound ---
        cursor.execute("""
            INSERT INTO workout_sessions
            (date, day_name, location, phase, duration_min, last_modified, modified_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (tomorrow, "Test Day - Heavy Compound", "Gym", "Foundation", 70, now, "test_seed"))
        s2 = cursor.lastrowid

        cursor.execute("""
            INSERT INTO session_blocks (session_id, position, block_type, title)
            VALUES (?, ?, ?, ?)
        """, (s2, 0, "warmup", "Stability Start"))
        b2_warmup = cursor.lastrowid

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (s2, b2_warmup, "warmup_0", 0, "Stability Start", "checklist"))
        e2_warmup = cursor.lastrowid

        for i, item in enumerate(["Cat-Cow x10", "Bird-Dog x5/side", "Dead Bug x10"]):
            cursor.execute(
                "INSERT INTO checklist_items (exercise_id, position, item_text) VALUES (?, ?, ?)",
                (e2_warmup, i, item)
            )

        cursor.execute("""
            INSERT INTO session_blocks (session_id, position, block_type, title)
            VALUES (?, ?, ?, ?)
        """, (s2, 1, "strength", "Heavy Compound"))
        b2_strength = cursor.lastrowid

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type,
             target_sets, target_reps, guidance_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (s2, b2_strength, "ex_1", 0, "Trap Bar Deadlift", "strength",
              4, "5", "RPE 7-8. Warm up: Bar only, 50%, 70%."))

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type,
             target_sets, target_reps, guidance_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (s2, b2_strength, "ex_2", 1, "Assisted Dips", "strength",
              3, "6-8", "RPE 7-8. Control descent 2 sec."))

        cursor.execute("""
            INSERT INTO session_blocks (session_id, position, block_type, title)
            VALUES (?, ?, ?, ?)
        """, (s2, 2, "cardio", "Conditioning"))
        b2_cardio = cursor.lastrowid

        cursor.execute("""
            INSERT INTO planned_exercises
            (session_id, block_id, exercise_key, position, name, exercise_type,
             target_duration_min, guidance_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (s2, b2_cardio, "cardio_1", 0, "Zone 2 Elliptical", "duration",
              25, "Maintain HR 135-148. Reduce resistance if HR rises."))

        # --- Yesterday's log (no plan for yesterday) ---
        cursor.execute("""
            INSERT INTO workout_session_logs
            (session_id, date, pain_discomfort, general_notes, last_modified, modified_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (None, yesterday, "Minor knee tightness, resolved after warmup",
              "Good energy, felt strong on squats", now, "test_seed"))
        log_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO exercise_logs
            (session_log_id, exercise_id, exercise_key, completed)
            VALUES (?, ?, ?, ?)
        """, (log_id, None, "warmup_1", 0))
        warmup_log_id = cursor.lastrowid

        for item in ["Cat-Cow x10", "Bird-Dog x5/side", "Dead Bug x10"]:
            cursor.execute(
                "INSERT INTO checklist_log_items (exercise_log_id, item_text) VALUES (?, ?)",
                (warmup_log_id, item)
            )

        cursor.execute("""
            INSERT INTO exercise_logs
            (session_log_id, exercise_id, exercise_key, completed, user_note)
            VALUES (?, ?, ?, ?, ?)
        """, (log_id, None, "ex_1", 1, "Used 53lb KB, felt solid"))
        ex1_log_id = cursor.lastrowid

        for set_num, weight, reps, rpe, unit in [
            (1, 53, 10, 6, "lbs"), (2, 53, 10, 7, "lbs"), (3, 53, 10, 7.5, "lbs"),
        ]:
            cursor.execute("""
                INSERT INTO set_logs (exercise_log_id, set_num, weight, reps, rpe, unit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ex1_log_id, set_num, weight, reps, rpe, unit))

        cursor.execute("""
            INSERT INTO exercise_logs
            (session_log_id, exercise_id, exercise_key, completed)
            VALUES (?, ?, ?, ?)
        """, (log_id, None, "ex_2", 1))
        ex2_log_id = cursor.lastrowid

        for set_num, weight, reps, rpe, unit in [
            (1, 45, 10, 6, "lbs"), (2, 45, 10, 7, "lbs"), (3, 45, 10, 7, "lbs"),
        ]:
            cursor.execute("""
                INSERT INTO set_logs (exercise_log_id, set_num, weight, reps, rpe, unit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ex2_log_id, set_num, weight, reps, rpe, unit))

        cursor.execute("""
            INSERT INTO exercise_logs
            (session_log_id, exercise_id, exercise_key, completed,
             duration_min, avg_hr, max_hr)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (log_id, None, "cardio_1", 1, 16, 142, 151))

        conn.commit()

    print(f"  Seeded test data:")
    print(f"    - Today's plan ({today}): Test Day - Lower Body + Conditioning")
    print(f"    - Tomorrow's plan ({tomorrow}): Test Day - Heavy Compound")
    print(f"    - Yesterday's log ({yesterday}): completed workout")


if __name__ == "__main__":
    import argparse
    import os
    import uvicorn

    parser = argparse.ArgumentParser(description="Coach Exercise Tracker Server")
    parser.add_argument("--test", action="store_true", help="Run in testing mode (port 8003, separate database)")
    parser.add_argument("--port", type=int, help="Override the port number")
    args = parser.parse_args()

    # Configure for test mode via environment variable
    if args.test:
        os.environ["COACH_TEST_MODE"] = "true"
        print(f"Starting in TEST MODE")
        print(f"  Database: {get_database_path()}")
        print(f"  Port: {args.port or 8003}")

    port = args.port if args.port else (8003 if args.test else 8002)
    uvicorn.run(app, host="0.0.0.0", port=port)
