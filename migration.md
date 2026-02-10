# Database Migration: JSON Blobs to Relational Tables

## Overview

This migration converts the Coach database from JSON blob storage (`workout_plans`, `workout_logs`) to normalized relational tables (`workout_sessions`, `session_blocks`, `planned_exercises`, etc.).

After migration, individual exercises, sets, and log entries are directly queryable via SQL without deserializing JSON blobs.

## Prerequisites

- Python 3.10+ with sqlite3
- Access to the production database file (`coach.db` or `coach-prod.db`)
- The migration script: `bin/migrate_to_rdb.py`

## Migration Steps

### 1. Back Up the Database

```bash
cp coach.db coach.db.backup-$(date +%Y%m%d)
# or for production:
cp coach-prod.db coach-prod.db.backup-$(date +%Y%m%d)
```

### 2. Dry Run (Preview)

Run the migration in dry-run mode first to see what will happen without making changes:

```bash
python bin/migrate_to_rdb.py --db-path coach.db --dry-run
```

This shows:
- How many plans will be migrated
- How many have blocks vs flat-only format
- How many exercises and logs will be created
- Any warnings about data issues

### 3. Run the Migration

```bash
python bin/migrate_to_rdb.py --db-path coach.db
```

The script:
1. Creates new relational tables alongside existing ones
2. Migrates all plans from `workout_plans` into `workout_sessions` + `session_blocks` + `planned_exercises` + `checklist_items`
3. Migrates all logs from `workout_logs` into `workout_session_logs` + `exercise_logs` + `set_logs` + `checklist_log_items`
4. Renames old tables to `workout_plans_legacy` and `workout_logs_legacy`
5. Validates row counts match

If validation fails, the script rolls back automatically.

### 4. Verify the Migration

Check the new tables in SQLite:

```bash
sqlite3 coach.db
```

```sql
-- Count sessions vs legacy plans
SELECT COUNT(*) FROM workout_sessions;
SELECT COUNT(*) FROM workout_plans_legacy;

-- Verify exercises are properly linked to blocks
SELECT COUNT(*) FROM planned_exercises WHERE block_id IS NULL;
-- Should return 0

-- Spot check a plan
SELECT ws.date, ws.day_name, sb.block_type, sb.title, pe.name, pe.exercise_type
FROM workout_sessions ws
JOIN session_blocks sb ON ws.id = sb.session_id
JOIN planned_exercises pe ON sb.id = pe.block_id
ORDER BY ws.date DESC, sb.position, pe.position
LIMIT 20;

-- Spot check a log
SELECT wsl.date, el.exercise_key, el.completed, sl.weight, sl.reps, sl.rpe
FROM workout_session_logs wsl
JOIN exercise_logs el ON wsl.id = el.session_log_id
LEFT JOIN set_logs sl ON el.id = sl.exercise_log_id
ORDER BY wsl.date DESC
LIMIT 20;
```

### 5. Start the Updated Server

The updated server code reads/writes to the new relational tables. Start it normally:

```bash
python src/server.py
# or
python src/server.py --test
```

### 6. Clean Up Legacy Tables (After Confirming)

Once you've confirmed everything works correctly (plans display properly in the PWA, logs sync correctly):

```sql
DROP TABLE IF EXISTS workout_plans_legacy;
DROP TABLE IF EXISTS workout_logs_legacy;
```

## What Changed

### New Tables

| Table | Replaces | Purpose |
|---|---|---|
| `workout_sessions` | `workout_plans` | One row per scheduled workout day (metadata only) |
| `session_blocks` | (embedded in JSON) | Block groupings within a session |
| `planned_exercises` | (embedded in JSON) | Individual exercises, directly queryable |
| `checklist_items` | (embedded in JSON) | Normalized checklist items for warmup exercises |
| `workout_session_logs` | `workout_logs` | Session-level log data (feedback) |
| `exercise_logs` | (embedded in JSON) | Per-exercise completion data |
| `set_logs` | (embedded in JSON) | Individual set data (weight, reps, RPE) |
| `checklist_log_items` | (embedded in JSON) | Completed checklist items |

### Flat Plans Handling

Plans that had only a flat `exercises[]` array (no blocks) are automatically wrapped into synthetic blocks:
- Checklist exercises -> `warmup` block
- Strength/circuit exercises -> `strength` block
- Duration/interval exercises -> `cardio` block

### Behavioral Changes

- `set_workout_plan` MCP tool now **requires** blocks (flat `exercises`-only format is rejected)
- `add_exercise` MCP tool now takes a `block_position` parameter
- PWA `WorkoutView` always renders via `BlockView` (flat exercise list fallback removed)
- Logs with `completed: false` will not include `completed` key when assembled (functionally equivalent)

## Rollback

If something goes wrong after migration:

### Before dropping legacy tables

If the legacy tables still exist:

```bash
# Restore from legacy tables
sqlite3 coach.db <<'SQL'
DROP TABLE IF EXISTS workout_sessions;
DROP TABLE IF EXISTS session_blocks;
DROP TABLE IF EXISTS planned_exercises;
DROP TABLE IF EXISTS checklist_items;
DROP TABLE IF EXISTS workout_session_logs;
DROP TABLE IF EXISTS exercise_logs;
DROP TABLE IF EXISTS set_logs;
DROP TABLE IF EXISTS checklist_log_items;
ALTER TABLE workout_plans_legacy RENAME TO workout_plans;
ALTER TABLE workout_logs_legacy RENAME TO workout_logs;
SQL
```

Then revert to the pre-migration code on the `main` branch.

### From backup

If you have the backup file:

```bash
cp coach.db.backup-YYYYMMDD coach.db
```

## New Query Examples

With the relational schema, previously impossible queries are now trivial:

```sql
-- Weight progression for a specific exercise
SELECT ws.date, sl.weight, sl.reps, sl.rpe
FROM set_logs sl
JOIN exercise_logs el ON sl.exercise_log_id = el.id
JOIN planned_exercises pe ON el.exercise_id = pe.id
JOIN workout_sessions ws ON pe.session_id = ws.id
WHERE pe.name = 'KB Goblet Squat'
ORDER BY ws.date, sl.set_num;

-- Cardio HR trends
SELECT ws.date, el.avg_hr, el.max_hr, el.duration_min
FROM exercise_logs el
JOIN planned_exercises pe ON el.exercise_id = pe.id
JOIN workout_sessions ws ON pe.session_id = ws.id
WHERE pe.exercise_type = 'duration'
ORDER BY ws.date;

-- Completion rate by phase
SELECT ws.phase,
       COUNT(DISTINCT ws.date) AS planned,
       COUNT(DISTINCT wsl.date) AS completed
FROM workout_sessions ws
LEFT JOIN workout_session_logs wsl ON ws.id = wsl.session_id
GROUP BY ws.phase;
```
