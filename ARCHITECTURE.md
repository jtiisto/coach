# Architecture

This document describes the technical architecture of the Coach Exercise Tracker application.

## System Overview

Coach is a full-stack workout planning and logging system with three main components:

```
┌─────────────────────────────────────────────────────────────────┐
│                         LLM (Claude)                            │
│                              │                                  │
│                         MCP Protocol                            │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    MCP Server                            │   │
│  │              (src/coach_mcp/server.py)                   │   │
│  │                         │                                │   │
│  │    ┌────────────────────┴────────────────────┐          │   │
│  │    │           DatabaseManager               │          │   │
│  │    └────────────────────┬────────────────────┘          │   │
│  └─────────────────────────┼────────────────────────────────┘   │
│                            │                                    │
│  ┌─────────────────────────┼────────────────────────────────┐   │
│  │                    SQLite Database                       │   │
│  │                     (coach.db)                           │   │
│  └─────────────────────────┼────────────────────────────────┘   │
│                            │                                    │
│  ┌─────────────────────────┼────────────────────────────────┐   │
│  │               FastAPI REST Server                        │   │
│  │                 (src/server.py)                          │   │
│  └─────────────────────────┼────────────────────────────────┘   │
│                            │                                    │
│                       HTTP/REST                                 │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    PWA Frontend                          │   │
│  │                 (public/js/app.js)                       │   │
│  │                         │                                │   │
│  │    ┌────────────────────┴────────────────────┐          │   │
│  │    │      LocalForage (IndexedDB)            │          │   │
│  │    └─────────────────────────────────────────┘          │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. MCP Server (`src/coach_mcp/`)

The Model Context Protocol server enables LLM-controlled workout plan management.

#### Files
- `server.py` - Tool definitions and database operations
- `config.py` - Configuration dataclass with validation

#### Key Classes

```python
class MCPConfig:
    """Configuration for MCP server."""
    db_path: Path
    max_rows: int = 1000
    strict_validation: bool = True
    transport: str = "stdio"

class DatabaseManager:
    """Manages SQLite connections with read/write separation."""
    def execute_query(query, params, read_only=True) -> List[Dict]
    def execute_write(query, params) -> int
    def transaction() -> ContextManager  # Multi-statement atomic writes

class SQLiteConnection:
    """Context manager for SQLite connections."""
    # Uses URI mode for read-only connections: file:path?mode=ro
```

#### Tool Categories

**Read Operations** (read-only database access):
- `get_workout_plan(start_date, end_date)` - Retrieve plans
- `get_workout_logs(start_date, end_date)` - Retrieve logs
- `list_scheduled_dates(start_date?, end_date?)` - List planned dates
- `get_workout_summary(days)` - Statistics

**Write Operations** (full database access):
- `set_workout_plan(date, plan)` - Create/replace plan
- `delete_workout_plan(date)` - Delete plan
- `update_plan_metadata(date, updates)` - Modify plan fields
- `add_exercise(date, exercise, block_position)` - Insert exercise into block
- `update_exercise(date, exercise_id, updates)` - Modify exercise
- `remove_exercise(date, exercise_id)` - Delete exercise
- `ingest_training_program(plans, transform_blocks?)` - Bulk import

### 2. REST Server (`src/server.py`)

FastAPI server providing the REST API for the PWA.

#### Endpoints

```
GET  /api/workout/status         → {lastSyncTime}
POST /api/workout/register       → {clientId, serverTime}
GET  /api/workout/sync           → {plans, logs, serverTime}
POST /api/workout/sync           → {appliedLogs, serverTime}
GET  /exercise                   → index.html (PWA entry)
GET  /styles.css                 → Stylesheet
GET  /js/{path}                  → JavaScript modules
```

#### Sync Protocol

**Download Sync** (`GET /api/workout/sync`):
```
Client: GET /api/workout/sync?client_id=X&last_sync_time=T
Server: Returns all plans + logs modified since T
        (or last 30 days if no last_sync_time)
```

**Upload Sync** (`POST /api/workout/sync`):
```
Client: POST {clientId, logs: {date: logData, ...}}
Server: Applies logs using last-write-wins
        Returns applied logs and serverTime
```

#### CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development-friendly
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3. Database Schema

SQLite database with normalized relational tables. All child tables use `ON DELETE CASCADE`.

```sql
-- Plan tables (server-authoritative)
CREATE TABLE workout_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,         -- YYYY-MM-DD
    day_name TEXT NOT NULL,
    location TEXT, phase TEXT,
    duration_min INTEGER,
    last_modified TEXT NOT NULL,        -- ISO-8601 UTC
    modified_by TEXT, extra TEXT
);

CREATE TABLE session_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    block_type TEXT NOT NULL,           -- warmup, strength, circuit, cardio, etc.
    title TEXT, duration_min INTEGER,
    rest_guidance TEXT, rounds INTEGER,
    UNIQUE(session_id, position)
);

CREATE TABLE planned_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    block_id INTEGER NOT NULL REFERENCES session_blocks(id) ON DELETE CASCADE,
    exercise_key TEXT NOT NULL,         -- e.g. "strength_1_1", "warmup_0"
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    exercise_type TEXT NOT NULL,        -- strength, duration, checklist, etc.
    target_sets INTEGER, target_reps TEXT,
    target_duration_min INTEGER, target_duration_sec INTEGER,
    rounds INTEGER, work_duration_sec INTEGER, rest_duration_sec INTEGER,
    guidance_note TEXT,
    hide_weight INTEGER DEFAULT 0, show_time INTEGER DEFAULT 0,
    extra TEXT,
    UNIQUE(session_id, exercise_key)
);

CREATE TABLE checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES planned_exercises(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    item_text TEXT NOT NULL,
    UNIQUE(exercise_id, position)
);

-- Log tables (user-controlled, last-write-wins)
CREATE TABLE workout_session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES workout_sessions(id),
    date TEXT NOT NULL UNIQUE,
    pain_discomfort TEXT, general_notes TEXT,
    last_modified TEXT NOT NULL,
    modified_by TEXT, extra TEXT
);

CREATE TABLE exercise_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_log_id INTEGER NOT NULL REFERENCES workout_session_logs(id) ON DELETE CASCADE,
    exercise_id INTEGER REFERENCES planned_exercises(id),
    exercise_key TEXT NOT NULL,
    completed INTEGER DEFAULT 0,
    user_note TEXT,
    duration_min REAL, avg_hr INTEGER, max_hr INTEGER,
    extra TEXT
);

CREATE TABLE set_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_log_id INTEGER NOT NULL REFERENCES exercise_logs(id) ON DELETE CASCADE,
    set_num INTEGER NOT NULL,
    weight REAL, reps INTEGER, rpe REAL,
    unit TEXT DEFAULT 'lbs',
    duration_sec REAL, completed INTEGER DEFAULT 0,
    extra TEXT
);

CREATE TABLE checklist_log_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_log_id INTEGER NOT NULL REFERENCES exercise_logs(id) ON DELETE CASCADE,
    item_text TEXT NOT NULL
);

-- Client tracking
CREATE TABLE clients (
    id TEXT PRIMARY KEY,
    name TEXT,
    last_seen_at TEXT
);

-- Sync metadata
CREATE TABLE meta_sync (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

### 4. Frontend Architecture

Preact-based PWA with signals for state management.

#### Technology Stack
- **Framework**: Preact 10.19.3
- **State**: @preact/signals
- **Storage**: localforage (IndexedDB wrapper)
- **Templating**: htm (tagged template literals)

#### Component Hierarchy

```
App
├── Header
│   └── SyncStatusIcon
├── CalendarPicker
│   └── CalendarModal
├── WorkoutView
│   ├── BlockView
│   │   └── ExerciseItem
│   │       ├── SetEntry (strength/circuit)
│   │       ├── CardioEntry (duration)
│   │       └── ChecklistEntry (checklist)
│   └── SessionFeedback
└── Notifications
```

#### State Management (store.js)

```javascript
// Reactive signals
const selectedDate = signal(getTodayString());
const workoutPlans = signal({});   // {date: planJson}
const workoutLogs = signal({});    // {date: logJson}
const syncMetadata = signal({
    clientId: null,
    lastServerSyncTime: null,
    dirtyDates: []
});
const isSyncing = signal(false);
const syncStatus = signal('unknown');  // 'green' | 'red' | 'gray'

// LocalForage keys
const STORAGE_KEYS = {
    metadata: 'coach_metadata',
    plans: 'workout_plans',
    logs: 'workout_logs',
    clientId: 'coach_client_id'
};
```

#### Sync Flow

```
User completes exercise
        ↓
updateLog() → workoutLogs signal updated
        ↓
Date marked dirty in syncMetadata
        ↓
triggerSync() debounced
        ↓
POST /api/workout/sync (upload logs)
        ↓
GET /api/workout/sync (download plans)
        ↓
Merge results → Clear dirty flags
        ↓
syncStatus = 'green'
```

## Data Structures

### Plan Object

Plans always contain a `blocks` array. Each block groups related exercises.

```json
{
    "day_name": "Lower Body + Conditioning",
    "location": "Home",
    "phase": "Foundation",
    "total_duration_min": 60,
    "blocks": [
        {
            "block_index": 0,
            "block_type": "warmup",
            "title": "The Stability Start",
            "exercises": [...]
        },
        {
            "block_index": 1,
            "block_type": "strength",
            "title": "Strength Block",
            "rest_guidance": "Rest until HR <= 130",
            "exercises": [...]
        },
        {
            "block_index": 2,
            "block_type": "cardio",
            "title": "Conditioning",
            "exercises": [...]
        }
    ]
}
```

### Exercise Types

```json
// strength
{"id": "ex_1", "name": "Squat", "type": "strength",
 "target_sets": 3, "target_reps": "10", "guidance_note": "Tempo 3-1-1"}

// duration
{"id": "cardio_1", "name": "Zone 2 Bike", "type": "duration",
 "target_duration_min": 15, "guidance_note": "HR 135-148"}

// checklist
{"id": "warmup_1", "name": "Warmup", "type": "checklist",
 "items": ["Cat-Cow x10", "Bird-Dog x5/side"]}

// weighted_time
{"id": "ex_5", "name": "Carry", "type": "weighted_time",
 "target_duration_sec": 60}

// interval
{"id": "hiit_1", "name": "Intervals", "type": "interval",
 "rounds": 4, "work_duration_sec": 30, "rest_duration_sec": 90}
```

### Log Object

```json
{
    "session_feedback": {
        "pain_discomfort": "Minor knee tightness",
        "general_notes": "Good energy"
    },
    "ex_1": {
        "completed": true,
        "user_note": "Used 53lb KB",
        "sets": [
            {"set_num": 1, "weight": 53, "reps": 10, "rpe": 6, "unit": "lbs"}
        ]
    },
    "cardio_1": {
        "completed": true,
        "duration_min": 16,
        "avg_hr": 142,
        "max_hr": 151
    }
}
```

## Block Transform System

Both `set_workout_plan` and `ingest_training_program` accept LLM-friendly block format and auto-transform it when `_needs_transform()` detects raw LLM format (exercises missing `id` or `type` fields, or cardio blocks with instruction text).

The transform (`_transform_block_plan()`) normalizes blocks in-place:

```
Raw LLM Block Format              Transformed Block Format
────────────────────              ────────────────────────
{                                 {
  "blocks": [                       "blocks": [
    {                                 {
      "block_type": "warmup",           "block_type": "warmup",
      "title": "Start",                 "title": "Start",
      "exercises": [                    "exercises": [
        {"name": "Stretch"}               {"id": "warmup_0", "name": "Start",
      ]                                    "type": "checklist",
    }                                      "items": ["Stretch"]}
  ]                                     ]
}                                     }
                                    ]
                                  }
```

Transform logic in `_transform_block_plan()`:
1. Warmup blocks → Single checklist exercise with items from block exercises
2. Strength/accessory blocks → Individual strength exercises with generated IDs
3. Circuit/power blocks → Circuit exercises with `target_sets` from block-level `rounds`
4. Cardio blocks with instructions → Duration/interval exercises
5. The optional `equipment` field on exercises (`"bodyweight"`, `"band"`, `"kettlebell"`, `"dumbbell"`, `"barbell"`, `"machine"`, `"cable"`) drives `hide_weight`. Values `"bodyweight"` and `"band"` set `hide_weight: true`. When `equipment` is absent, the name-based heuristic (`_is_bodyweight_or_band()`) is used as a fallback.

Circuit and power blocks use an explicit `rounds` field at the block level to specify how many rounds to complete. This is passed through as `target_sets` on each exercise in the block. If an exercise has its own `sets` field, it takes precedence over block-level `rounds`.

## Security Considerations

### Database Access
- MCP tools use parameterized queries (SQL injection prevention)
- Read operations use read-only SQLite connections
- Write operations validate input structure

### Client Sync
- Client IDs are UUIDs generated on first connection
- Last-write-wins for logs (no conflict resolution needed)
- Plans are server-authoritative (clients only read)

### CORS
- Currently allows all origins for development
- Production should restrict to specific domains

## Testing Architecture

```
test/
├── conftest.py              # Shared fixtures, test DB setup
├── unit/
│   ├── test_database.py     # Database schema and table tests
│   └── test_transform.py    # Block transform and exercise rendering tests
└── integration/
    ├── test_mcp_tools.py    # All MCP tool tests
    ├── test_sync.py         # POST /api/workout/sync (log upload) tests
    ├── test_sync_full.py    # GET /api/workout/sync (full sync) tests
    └── test_static_files.py # Static file serving and CORS tests
```

### Test Database
- Separate `coach_test.db` when `COACH_TEST_MODE=true`
- Auto-seeded with sample workouts (today, yesterday, tomorrow)
- Cleaned between test runs

## Deployment

### Development
```bash
export COACH_DB_PATH=./coach.db
python -m src.server
```

### Production
```bash
export COACH_DB_PATH=/var/lib/coach/coach.db
uvicorn src.server:app --host 0.0.0.0 --port 8002
```

### MCP Server
Runs via stdio transport, configured in Claude desktop config:
```json
{
  "mcpServers": {
    "coach": {
      "command": "python",
      "args": ["-m", "src.coach_mcp.server"],
      "env": {"COACH_DB_PATH": "/path/to/coach.db"}
    }
  }
}
```

## Future Considerations

### Scalability
- SQLite is sufficient for single-user/small team use
- For multi-user: migrate to PostgreSQL, add authentication

### Offline-First Enhancement
- Service Worker for full offline PWA
- Background sync API for deferred uploads

### Additional MCP Tools
- `duplicate_workout_plan` - Copy plan to new date
- `get_exercise_history` - Track specific exercise over time
- `suggest_progression` - AI-powered load recommendations
