#!/usr/bin/env python3
"""
Migrate Coach database from JSON blobs (workout_plans/workout_logs)
to normalized relational tables (workout_sessions, session_blocks, etc.).

Usage:
    python bin/migrate_to_rdb.py [--db-path coach.db] [--dry-run]

The script:
1. Creates new relational tables alongside existing ones
2. Migrates plan data from workout_plans → workout_sessions + session_blocks + planned_exercises
3. Migrates log data from workout_logs → workout_session_logs + exercise_logs + set_logs
4. Renames old tables to *_legacy for rollback safety
5. Validates row counts
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def create_new_schema(cursor):
    """Create the new relational tables."""
    cursor.execute("PRAGMA foreign_keys = ON")

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checklist_log_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_log_id INTEGER NOT NULL REFERENCES exercise_logs(id) ON DELETE CASCADE,
            item_text       TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checklist_log_items_exercise ON checklist_log_items(exercise_log_id)")

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


def wrap_flat_exercises_into_blocks(exercises):
    """Wrap flat exercises into synthetic blocks grouped by type."""
    blocks = []
    current_block_type = None
    current_exercises = []

    type_to_block = {
        "checklist": "warmup",
        "strength": "strength",
        "circuit": "circuit",
        "duration": "cardio",
        "interval": "cardio",
        "weighted_time": "strength",
        "power": "power",
        "accessory": "accessory",
    }

    block_titles = {
        "warmup": "Warmup",
        "strength": "Strength Block",
        "circuit": "Circuit Block",
        "cardio": "Cardio",
        "power": "Power Block",
        "accessory": "Accessory Block",
    }

    for ex in exercises:
        ex_type = ex.get("type", "strength")
        block_type = type_to_block.get(ex_type, "strength")

        if block_type != current_block_type:
            if current_exercises:
                blocks.append({
                    "block_type": current_block_type,
                    "title": block_titles.get(current_block_type, "Block"),
                    "exercises": current_exercises,
                })
            current_block_type = block_type
            current_exercises = []

        current_exercises.append(ex)

    if current_exercises:
        blocks.append({
            "block_type": current_block_type,
            "title": block_titles.get(current_block_type, "Block"),
            "exercises": current_exercises,
        })

    return blocks


def migrate_plans(cursor, dry_run=False):
    """Migrate workout_plans to relational tables."""
    cursor.execute("SELECT date, plan_json, last_modified, last_modified_by FROM workout_plans")
    plans = cursor.fetchall()

    stats = {"total": 0, "with_blocks": 0, "flat_only": 0, "exercises": 0, "warnings": []}

    for plan_row in plans:
        date_str = plan_row[0]
        plan_json = plan_row[1]
        last_modified = plan_row[2]
        modified_by = plan_row[3]
        stats["total"] += 1

        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError:
            stats["warnings"].append(f"  WARNING: Invalid JSON for plan {date_str}, skipping")
            continue

        day_name = plan.get("day_name", plan.get("theme", "Workout"))
        location = plan.get("location")
        phase = plan.get("phase")
        duration_min = plan.get("total_duration_min")

        # Determine blocks
        if "blocks" in plan and plan["blocks"]:
            blocks = plan["blocks"]
            stats["with_blocks"] += 1
        elif "exercises" in plan and plan["exercises"]:
            blocks = wrap_flat_exercises_into_blocks(plan["exercises"])
            stats["flat_only"] += 1
        else:
            stats["warnings"].append(f"  WARNING: Plan {date_str} has no blocks or exercises, skipping")
            continue

        if dry_run:
            for block in blocks:
                stats["exercises"] += len(block.get("exercises", []))
            continue

        # Insert session
        cursor.execute("""
            INSERT INTO workout_sessions
            (date, day_name, location, phase, duration_min, last_modified, modified_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (date_str, day_name, location, phase, duration_min, last_modified, modified_by))
        session_id = cursor.lastrowid

        # Insert blocks and exercises
        for i, block in enumerate(blocks):
            cursor.execute("""
                INSERT INTO session_blocks
                (session_id, position, block_type, title, duration_min, rest_guidance, rounds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, block.get("block_index", i),
                block.get("block_type", "strength"),
                block.get("title"),
                block.get("duration_min"),
                block.get("rest_guidance", ""),
                block.get("rounds"),
            ))
            block_id = cursor.lastrowid

            for j, ex in enumerate(block.get("exercises", [])):
                exercise_key = ex.get("id", f"{block.get('block_type', 'ex')}_{i}_{j}")
                cursor.execute("""
                    INSERT INTO planned_exercises
                    (session_id, block_id, exercise_key, position, name, exercise_type,
                     target_sets, target_reps, target_duration_min, target_duration_sec,
                     rounds, work_duration_sec, rest_duration_sec,
                     guidance_note, hide_weight, show_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, block_id, exercise_key, j,
                    ex.get("name", "Unknown"),
                    ex.get("type", "strength"),
                    ex.get("target_sets"),
                    ex.get("target_reps"),
                    ex.get("target_duration_min"),
                    ex.get("target_duration_sec"),
                    ex.get("rounds"),
                    ex.get("work_duration_sec"),
                    ex.get("rest_duration_sec"),
                    ex.get("guidance_note"),
                    1 if ex.get("hide_weight") else 0,
                    1 if ex.get("show_time") else 0,
                ))
                exercise_id = cursor.lastrowid
                stats["exercises"] += 1

                # Checklist items
                if ex.get("type") == "checklist":
                    for k, item in enumerate(ex.get("items", [])):
                        cursor.execute("""
                            INSERT INTO checklist_items (exercise_id, position, item_text)
                            VALUES (?, ?, ?)
                        """, (exercise_id, k, item))

                # Check for duplicate exercise keys
                cursor.execute("""
                    SELECT COUNT(*) FROM planned_exercises
                    WHERE session_id = ? AND exercise_key = ?
                """, (session_id, exercise_key))
                count = cursor.fetchone()[0]
                if count > 1:
                    stats["warnings"].append(
                        f"  WARNING: Duplicate exercise_key '{exercise_key}' in plan {date_str}"
                    )

    return stats


def migrate_logs(cursor, dry_run=False):
    """Migrate workout_logs to relational tables."""
    cursor.execute("SELECT date, log_json, last_modified, last_modified_by FROM workout_logs")
    logs = cursor.fetchall()

    stats = {"total": 0, "exercise_logs": 0, "set_logs": 0, "warnings": []}
    meta_keys = {"session_feedback", "_lastModifiedAt", "_lastModifiedBy"}

    for log_row in logs:
        date_str = log_row[0]
        log_json = log_row[1]
        last_modified = log_row[2]
        modified_by = log_row[3]
        stats["total"] += 1

        try:
            log = json.loads(log_json)
        except json.JSONDecodeError:
            stats["warnings"].append(f"  WARNING: Invalid JSON for log {date_str}, skipping")
            continue

        if dry_run:
            for key, val in log.items():
                if key not in meta_keys and isinstance(val, dict):
                    stats["exercise_logs"] += 1
                    stats["set_logs"] += len(val.get("sets", []))
            continue

        # Extract session feedback
        feedback = log.get("session_feedback", {})
        pain = feedback.get("pain_discomfort")
        notes = feedback.get("general_notes")

        # Map _lastModified* to proper fields
        if not last_modified:
            last_modified = log.get("_lastModifiedAt", "")
        if not modified_by:
            modified_by = log.get("_lastModifiedBy")

        # Find matching session
        cursor.execute("SELECT id FROM workout_sessions WHERE date = ?", (date_str,))
        session_row = cursor.fetchone()
        session_id = session_row[0] if session_row else None

        # Insert session log
        cursor.execute("""
            INSERT INTO workout_session_logs
            (session_id, date, pain_discomfort, general_notes, last_modified, modified_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, date_str, pain, notes, last_modified or "", modified_by))
        session_log_id = cursor.lastrowid

        # Process exercise entries
        for exercise_key, exercise_data in log.items():
            if exercise_key in meta_keys:
                continue
            if not isinstance(exercise_data, dict):
                continue

            # Find planned_exercises.id for this key
            exercise_id = None
            if session_id:
                cursor.execute("""
                    SELECT id FROM planned_exercises
                    WHERE session_id = ? AND exercise_key = ?
                """, (session_id, exercise_key))
                ex_row = cursor.fetchone()
                if ex_row:
                    exercise_id = ex_row[0]

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
            stats["exercise_logs"] += 1

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
                stats["set_logs"] += 1

            # Store checklist items
            for item in exercise_data.get("completed_items", []):
                cursor.execute("""
                    INSERT INTO checklist_log_items (exercise_log_id, item_text)
                    VALUES (?, ?)
                """, (exercise_log_id, item))

    return stats


def validate_migration(cursor):
    """Validate migrated data by comparing counts."""
    issues = []

    # Count plans
    cursor.execute("SELECT COUNT(*) FROM workout_plans_legacy")
    old_plans = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM workout_sessions")
    new_plans = cursor.fetchone()[0]

    if old_plans != new_plans:
        issues.append(f"Plan count mismatch: {old_plans} legacy vs {new_plans} sessions")

    # Count logs
    cursor.execute("SELECT COUNT(*) FROM workout_logs_legacy")
    old_logs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM workout_session_logs")
    new_logs = cursor.fetchone()[0]

    if old_logs != new_logs:
        issues.append(f"Log count mismatch: {old_logs} legacy vs {new_logs} session_logs")

    # Verify every exercise has a block_id
    cursor.execute("SELECT COUNT(*) FROM planned_exercises WHERE block_id IS NULL")
    null_blocks = cursor.fetchone()[0]
    if null_blocks > 0:
        issues.append(f"{null_blocks} exercises with NULL block_id")

    # Verify dates match
    cursor.execute("""
        SELECT date FROM workout_plans_legacy
        EXCEPT
        SELECT date FROM workout_sessions
    """)
    missing = cursor.fetchall()
    if missing:
        issues.append(f"Missing session dates: {[r[0] for r in missing]}")

    return issues


def main():
    parser = argparse.ArgumentParser(description="Migrate Coach DB from JSON blobs to relational tables")
    parser.add_argument("--db-path", default="coach.db", help="Path to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without making changes")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    print(f"Migration: JSON blobs -> relational tables")
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    # Check if old tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workout_plans'")
    if not cursor.fetchone():
        print("ERROR: workout_plans table not found. Nothing to migrate.")
        conn.close()
        sys.exit(1)

    # Check if already migrated
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workout_sessions'")
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM workout_sessions")
        count = cursor.fetchone()[0]
        if count > 0:
            print("WARNING: workout_sessions table already has data.")
            print("  If re-migrating, drop new tables first or they will conflict.")
            conn.close()
            sys.exit(1)

    try:
        # Step 1: Create new schema
        print("Step 1: Creating new relational tables...")
        create_new_schema(cursor)
        if not args.dry_run:
            conn.commit()
        print("  Done.")

        # Step 2: Migrate plans
        print("\nStep 2: Migrating workout plans...")
        plan_stats = migrate_plans(cursor, dry_run=args.dry_run)
        print(f"  Plans: {plan_stats['total']} total")
        print(f"    With blocks: {plan_stats['with_blocks']}")
        print(f"    Flat-only (wrapped): {plan_stats['flat_only']}")
        print(f"    Exercises: {plan_stats['exercises']}")
        for w in plan_stats["warnings"]:
            print(w)

        # Step 3: Migrate logs
        print("\nStep 3: Migrating workout logs...")
        log_stats = migrate_logs(cursor, dry_run=args.dry_run)
        print(f"  Logs: {log_stats['total']} total")
        print(f"    Exercise logs: {log_stats['exercise_logs']}")
        print(f"    Set logs: {log_stats['set_logs']}")
        for w in log_stats["warnings"]:
            print(w)

        if args.dry_run:
            print("\n--- DRY RUN COMPLETE (no changes made) ---")
            conn.close()
            return

        # Step 4: Rename old tables to legacy
        print("\nStep 4: Renaming old tables to *_legacy...")
        cursor.execute("ALTER TABLE workout_plans RENAME TO workout_plans_legacy")
        cursor.execute("ALTER TABLE workout_logs RENAME TO workout_logs_legacy")
        print("  Done.")

        # Step 5: Validate
        print("\nStep 5: Validating migration...")
        issues = validate_migration(cursor)
        if issues:
            print("  VALIDATION ISSUES:")
            for issue in issues:
                print(f"    - {issue}")
            print("\n  Rolling back...")
            conn.rollback()
            # Restore old table names
            cursor.execute("ALTER TABLE workout_plans_legacy RENAME TO workout_plans")
            cursor.execute("ALTER TABLE workout_logs_legacy RENAME TO workout_logs")
            conn.commit()
            print("  Rollback complete. No changes were made.")
            conn.close()
            sys.exit(1)
        else:
            print("  All validations passed!")

        # Commit everything
        conn.commit()
        print("\nMigration complete!")
        print("  Old tables preserved as: workout_plans_legacy, workout_logs_legacy")
        print("  To drop legacy tables after confirming everything works:")
        print("    DROP TABLE workout_plans_legacy;")
        print("    DROP TABLE workout_logs_legacy;")

    except Exception as e:
        print(f"\nERROR: Migration failed: {e}")
        conn.rollback()
        print("  Rolled back all changes.")
        conn.close()
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
