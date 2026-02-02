# Coach Exercise Tracker

A full-stack workout planning and logging application with LLM integration via Model Context Protocol (MCP).

## Overview

Coach is designed for personalized workout management:
- **Workout Plans** are server-authoritative and managed by LLMs through MCP
- **Workout Logs** are user-controlled via a mobile-first PWA
- **Sync** keeps plans and logs consistent across devices

## Features

- Mobile-first Progressive Web App (PWA)
- Offline-capable with automatic sync
- 6 exercise types: strength, duration, checklist, weighted_time, interval, circuit
- Heart rate and RPE tracking
- Calendar view with workout status indicators
- Dark theme optimized for gym use

## Quick Start

### Prerequisites

- Python 3.10+
- SQLite 3

### Installation

```bash
# Clone and install dependencies
git clone <repo-url>
cd coach
pip install -r requirements.txt
```

### Running the Server

```bash
# Start the server (default port 8002)
./bin/server.sh start

# Check server status
./bin/server.sh status

# View logs
./bin/server.sh logs

# Stop the server
./bin/server.sh stop

# Restart the server
./bin/server.sh restart
```

Access the PWA at `http://localhost:8002/exercise`

### Server Control Script

The `bin/server.sh` script provides full server lifecycle management:

| Command | Description |
|---------|-------------|
| `start` | Start the server in background |
| `stop` | Stop the running server |
| `status` | Check if server is running and healthy |
| `restart` | Stop and start the server |
| `logs` | Show last 50 lines of server logs |
| `follow` | Follow logs in real-time (Ctrl+C to exit) |

Use `--test` flag to run in test mode on port 8003:
```bash
./bin/server.sh --test start
```

### Running Tests

```bash
# Run all tests with test database
COACH_TEST_MODE=true pytest test/ -v
```

## MCP Integration

Coach provides a comprehensive MCP server for LLM-controlled workout plan management.

### Configuration

Add to your Claude desktop config (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "coach": {
      "command": "python",
      "args": ["-m", "src.coach_mcp.server"],
      "env": {
        "COACH_DB_PATH": "/path/to/coach.db"
      }
    }
  }
}
```

### MCP Tools

#### Plan Retrieval & Analysis

| Tool | Description |
|------|-------------|
| `get_workout_plan` | Fetch plans for a date range |
| `get_workout_logs` | Read completed workout logs (read-only) |
| `list_scheduled_dates` | List dates with scheduled plans |
| `get_workout_summary` | Get workout statistics and completion rates |

#### Plan Management

| Tool | Description |
|------|-------------|
| `set_workout_plan` | Create or replace a workout plan for a date |
| `delete_workout_plan` | Remove a workout plan |
| `update_plan_metadata` | Update plan-level fields (name, location, phase) |
| `ingest_training_program` | Bulk import multiple plans at once |

#### Exercise Management

| Tool | Description |
|------|-------------|
| `add_exercise` | Add an exercise to an existing plan |
| `update_exercise` | Modify exercise fields |
| `remove_exercise` | Remove an exercise from a plan |

#### Resources

| Resource | Description |
|----------|-------------|
| `coach_plan_guide` | Complete guide for creating workout plans |

### Example: Creating a Workout Plan

```python
# Using set_workout_plan MCP tool
set_workout_plan("2026-02-02", {
    "day_name": "Lower Body + Conditioning",
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
            "guidance_note": "Tempo 3-1-1. Rest until HR <= 130."
        },
        {
            "id": "cardio_1",
            "name": "Zone 2 Bike",
            "type": "duration",
            "target_duration_min": 15,
            "guidance_note": "HR 135-148"
        }
    ]
})
```

### Example: Bulk Ingestion

```python
# Using ingest_training_program with block format
ingest_training_program({
    "2026-02-02": {
        "phase": "Foundation",
        "theme": "Lower Body + Bike",
        "location": "Home",
        "total_duration_min": 60,
        "blocks": [
            {
                "block_type": "warmup",
                "title": "Stability Start",
                "exercises": [{"name": "Cat-Cow", "reps": 10}]
            },
            {
                "block_type": "strength",
                "title": "Main Lifts",
                "rest_guidance": "Rest until HR <= 130",
                "exercises": [
                    {"name": "KB Goblet Squat", "sets": 3, "reps": 10, "tempo": "3-1-1"}
                ]
            }
        ]
    }
}, transform_blocks=True)
```

### LLM Plan Generation Format

For detailed documentation on the block-based JSON format that LLMs should use when generating workout plans, see [llm_exercise_plan_format.md](llm_exercise_plan_format.md). This format is automatically transformed by `ingest_training_program` when `transform_blocks=True`.

## Exercise Types

### strength
Weight training with sets/reps:
```json
{"id": "ex_1", "name": "Squat", "type": "strength", "target_sets": 3, "target_reps": "10"}
```

### duration
Cardio with time targets:
```json
{"id": "cardio_1", "name": "Zone 2 Bike", "type": "duration", "target_duration_min": 15}
```

### checklist
Multi-item routines:
```json
{"id": "warmup_1", "name": "Warmup", "type": "checklist", "items": ["Item 1", "Item 2"]}
```

### weighted_time
Timed exercises with load:
```json
{"id": "ex_5", "name": "Farmer's Carry", "type": "weighted_time", "target_duration_sec": 60}
```

### interval
HIIT training:
```json
{"id": "hiit_1", "name": "Intervals", "type": "interval", "rounds": 4, "work_duration_sec": 30, "rest_duration_sec": 90}
```

### circuit
Circuit training (similar structure to strength)

## REST API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workout/status` | GET | Server sync status |
| `/api/workout/register` | POST | Register client device |
| `/api/workout/sync` | GET | Download plans and logs |
| `/api/workout/sync` | POST | Upload workout logs |
| `/exercise` | GET | PWA entry point |

## Project Structure

```
coach/
├── src/
│   ├── coach_mcp/          # MCP server module
│   │   ├── server.py       # MCP tools and server logic
│   │   └── config.py       # Configuration
│   └── server.py           # FastAPI REST server
├── public/                 # Frontend assets
│   ├── index.html
│   ├── styles.css
│   └── js/
│       ├── app.js          # Main Preact app
│       ├── store.js        # State management
│       └── components/     # UI components
├── bin/
│   ├── server.sh           # Server control script
│   ├── deploy-prod.sh      # Production deployment
│   └── ingest_plans.py     # Bulk ingestion CLI tool
├── test/                   # Test suite
├── llm_exercise_plan_format.md  # LLM plan generation guide
└── requirements.txt
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `COACH_DB_PATH` | Yes | Path to SQLite database |
| `COACH_TEST_MODE` | No | Set to "true" for test database |

## Development

### Code Style

- Python: Follow PEP 8
- JavaScript: Use Preact signals for state management
- All dates use YYYY-MM-DD format

### Testing

```bash
# Run all tests
COACH_TEST_MODE=true pytest test/ -v

# Run with coverage
COACH_TEST_MODE=true pytest test/ --cov=src --cov-report=html
```

## License

MIT
