"""Coach MCP Server implementation.

Provides access to workout plans (read-write) and logs (read-only)
through the Model Context Protocol for LLM workout planning and analysis.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "FastMCP is required for MCP server functionality. "
        "Install with: pip install fastmcp"
    )

from .config import MCPConfig


class SQLiteConnection:
    """SQLite connection context manager with configurable read/write mode."""

    def __init__(self, db_path: Path, read_only: bool = True):
        self.db_path = db_path
        self.read_only = read_only
        self.conn = None

    def __enter__(self):
        """Open SQLite connection."""
        if self.read_only:
            self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        else:
            self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection safely."""
        if self.conn:
            self.conn.close()


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, config: MCPConfig):
        self.config = config

    def get_connection(self, read_only: bool = True):
        """Get database connection."""
        return SQLiteConnection(self.config.db_path, read_only=read_only)

    def execute_query(
        self, query: str, params: Optional[List[Any]] = None, read_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Execute a query and return results."""
        try:
            with self.get_connection(read_only=read_only) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params or [])
                if not read_only:
                    conn.commit()
                results = [dict(row) for row in cursor.fetchall()]
                return results
        except sqlite3.Error as e:
            raise ValueError(f"Database error: {str(e)}")

    def execute_write(
        self, query: str, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a write query and return rows affected."""
        try:
            with self.get_connection(read_only=False) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params or [])
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            raise ValueError(f"Database error: {str(e)}")


def get_utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_mcp_server(config: Optional[MCPConfig] = None) -> FastMCP:
    """Create and configure the Coach MCP server."""
    if config is None:
        if "COACH_DB_PATH" not in os.environ:
            raise ValueError("COACH_DB_PATH environment variable must be set")

        db_path = Path(os.environ["COACH_DB_PATH"])
        config = MCPConfig.from_db_path(db_path)

    config.validate()
    db_manager = DatabaseManager(config)
    mcp = FastMCP("Coach Workout Manager")

    @mcp.tool()
    def get_workout_plan(
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """WHEN TO USE: When you need to see what workouts are scheduled.

        Retrieves workout plans for the specified date range. Use this to:
        - Check what's scheduled for upcoming days
        - Review the structure of existing plans
        - Get context before creating new plans

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of plans with date and full plan structure including exercises
        """
        try:
            query = """
                SELECT date, plan_json, last_modified
                FROM workout_plans
                WHERE date >= ? AND date <= ?
                ORDER BY date
            """
            results = db_manager.execute_query(query, [start_date, end_date])

            plans = []
            for row in results:
                plan_data = json.loads(row["plan_json"])
                plans.append({
                    "date": row["date"],
                    "last_modified": row["last_modified"],
                    "plan": plan_data
                })

            return plans
        except Exception as e:
            raise ValueError(f"Failed to get workout plans: {str(e)}")

    @mcp.tool()
    def get_workout_logs(
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """WHEN TO USE: When analyzing workout history or performance trends.

        Retrieves completed workout logs for the specified date range. Use this to:
        - Review what exercises were actually completed
        - Analyze performance data (weights, reps, RPE)
        - Track progress over time
        - Identify patterns in workout adherence

        This is READ-ONLY - logs are created by the user through the PWA.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of logs with date and exercise completion data
        """
        try:
            query = """
                SELECT date, log_json, last_modified
                FROM workout_logs
                WHERE date >= ? AND date <= ?
                ORDER BY date
            """
            results = db_manager.execute_query(query, [start_date, end_date])

            logs = []
            for row in results:
                log_data = json.loads(row["log_json"])
                logs.append({
                    "date": row["date"],
                    "last_modified": row["last_modified"],
                    "log": log_data
                })

            return logs
        except Exception as e:
            raise ValueError(f"Failed to get workout logs: {str(e)}")

    @mcp.tool()
    def set_workout_plan(
        date: str,
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """WHEN TO USE: When creating or updating a workout plan for a specific date.

        Creates or replaces the workout plan for the given date. Use this to:
        - Schedule new workouts
        - Update existing plans
        - Build out a multi-week training program

        The plan should follow the structured format with either a flat exercises
        list or block-based groupings (warmup/strength/cardio etc.). When blocks
        are provided without exercises, the exercises list is generated
        automatically via the block transform pipeline.

        Args:
            date: Target date (YYYY-MM-DD)
            plan: Plan object with **either** ``exercises`` or ``blocks`` (or both).

                Flat format:
                {
                    "day_name": "Lower Body + Bike",
                    "location": "Home" or "Gym",
                    "phase": "Foundation" or "Building" or "Intensity",
                    "exercises": [
                        {
                            "id": "unique_id",
                            "name": "Exercise Name",
                            "type": "strength" | "duration" | "checklist" | "weighted_time" | "interval",
                            "target_sets": 3,  # for strength
                            "target_reps": "10" or "8-10",  # for strength
                            "target_duration_min": 15,  # for duration/cardio
                            "items": ["item1", "item2"],  # for checklist
                            "guidance_note": "Tempo 3-1-1. Rest until HR <= 130."
                        }
                    ]
                }

                Block format:
                {
                    "day_name": "Upper Body Strength",
                    "location": "Gym",
                    "phase": "Building",
                    "blocks": [
                        {
                            "block_type": "warmup",
                            "title": "Warmup",
                            "exercises": [
                                {"name": "Arm Circles", "reps": 10},
                                {"name": "Band Pull-Aparts", "reps": 15}
                            ]
                        },
                        {
                            "block_type": "strength",
                            "title": "Main Lifts",
                            "rest_guidance": "Rest 2-3 min",
                            "exercises": [
                                {"name": "Bench Press", "sets": 4, "reps": "6-8"}
                            ]
                        },
                        {
                            "block_type": "cardio",
                            "title": "Zone 2 Cooldown",
                            "duration_min": 10,
                            "instructions": ["Easy pace on bike"]
                        }
                    ]
                }

        Returns:
            Success confirmation with the saved plan

        Examples:
            Flat format:
            set_workout_plan("2026-02-02", {
                "day_name": "Lower Body + Bike",
                "location": "Home",
                "phase": "Foundation",
                "exercises": [
                    {"id": "warmup_1", "name": "Stability Start", "type": "checklist",
                     "items": ["Cat-Cow x10", "Bird-Dog x5/side", "Dead Bug x10"]},
                    {"id": "ex_1", "name": "KB Goblet Squat", "type": "strength",
                     "target_sets": 3, "target_reps": "10", "guidance_note": "Tempo 3-1-1"}
                ]
            })

            Block format:
            set_workout_plan("2026-02-02", {
                "day_name": "Upper Body Strength",
                "location": "Gym",
                "phase": "Building",
                "blocks": [
                    {"block_type": "warmup", "title": "Warmup",
                     "exercises": [{"name": "Arm Circles", "reps": 10}]},
                    {"block_type": "strength", "title": "Main Lifts",
                     "exercises": [{"name": "Bench Press", "sets": 4, "reps": "6-8"}]}
                ]
            })
        """
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {date}. Use YYYY-MM-DD")

        # Validate plan structure
        if not isinstance(plan, dict):
            raise ValueError("Plan must be a dictionary")

        if "day_name" not in plan:
            raise ValueError("Plan missing required field: day_name")
        if "exercises" not in plan and "blocks" not in plan:
            raise ValueError("Plan must have either 'exercises' or 'blocks'")

        # When blocks provided without exercises, validate blocks and transform
        if "blocks" in plan and "exercises" not in plan:
            if not isinstance(plan["blocks"], list):
                raise ValueError("Plan blocks must be a list")

            valid_block_types = ["warmup", "strength", "cardio", "circuit", "accessory", "power"]
            for i, block in enumerate(plan["blocks"]):
                if "block_type" not in block:
                    raise ValueError(f"Block {i} missing 'block_type' field")
                if not isinstance(block["block_type"], str):
                    raise ValueError(f"Block {i} 'block_type' must be a string")
                if block["block_type"] not in valid_block_types:
                    raise ValueError(f"Block {i} has invalid block_type: {block['block_type']}. Must be one of: {valid_block_types}")
                if "exercises" not in block and "instructions" not in block:
                    raise ValueError(f"Block {i} must have either 'exercises' or 'instructions'")

            plan = _transform_block_plan(plan)

        if not isinstance(plan["exercises"], list):
            raise ValueError("Plan exercises must be a list")

        # Validate each exercise has required fields
        for i, exercise in enumerate(plan["exercises"]):
            if "id" not in exercise:
                raise ValueError(f"Exercise {i} missing 'id' field")
            if "name" not in exercise:
                raise ValueError(f"Exercise {i} missing 'name' field")
            if "type" not in exercise:
                raise ValueError(f"Exercise {i} missing 'type' field")

            valid_types = ["strength", "duration", "checklist", "weighted_time", "interval", "circuit"]
            if exercise["type"] not in valid_types:
                raise ValueError(f"Exercise {i} has invalid type: {exercise['type']}. Must be one of: {valid_types}")

        try:
            now = get_utc_now()
            plan_json = json.dumps(plan)

            query = """
                INSERT OR REPLACE INTO workout_plans (date, plan_json, last_modified, last_modified_by)
                VALUES (?, ?, ?, ?)
            """
            db_manager.execute_write(query, [date, plan_json, now, "mcp"])

            return {
                "success": True,
                "date": date,
                "last_modified": now,
                "plan": plan,
                "message": f"Workout plan for {date} saved successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to save workout plan: {str(e)}")

    @mcp.tool()
    def get_workout_summary(days: int = 30) -> Dict[str, Any]:
        """WHEN TO USE: When you want a quick overview of workout activity.

        Provides summary statistics about workout plans and completed logs.

        Args:
            days: Number of recent days to analyze (max 365, default: 30)

        Returns:
            Summary including planned vs completed workouts, exercise counts, etc.
        """
        if days > 365:
            raise ValueError("Days cannot exceed 365")

        try:
            start_date = (date.today() - timedelta(days=days)).isoformat()
            end_date = date.today().isoformat()

            # Count planned workouts
            plans_query = """
                SELECT COUNT(*) as count FROM workout_plans
                WHERE date >= ? AND date <= ?
            """
            plans_result = db_manager.execute_query(plans_query, [start_date, end_date])
            planned_count = plans_result[0]["count"] if plans_result else 0

            # Count completed workouts (logs exist)
            logs_query = """
                SELECT COUNT(*) as count FROM workout_logs
                WHERE date >= ? AND date <= ?
            """
            logs_result = db_manager.execute_query(logs_query, [start_date, end_date])
            completed_count = logs_result[0]["count"] if logs_result else 0

            # Get recent plans
            recent_plans_query = """
                SELECT date, plan_json FROM workout_plans
                WHERE date >= ? AND date <= ?
                ORDER BY date DESC
                LIMIT 7
            """
            recent_plans = db_manager.execute_query(recent_plans_query, [start_date, end_date])

            # Parse exercise counts from plans
            exercise_types = {}
            for row in recent_plans:
                plan = json.loads(row["plan_json"])
                for ex in plan.get("exercises", []):
                    ex_type = ex.get("type", "unknown")
                    exercise_types[ex_type] = exercise_types.get(ex_type, 0) + 1

            completion_rate = round(completed_count / planned_count * 100, 1) if planned_count > 0 else 0

            return {
                "analysis_period_days": days,
                "planned_workouts": planned_count,
                "completed_workouts": completed_count,
                "completion_rate_percent": completion_rate,
                "exercise_types_in_recent_plans": exercise_types,
                "recent_plan_dates": [row["date"] for row in recent_plans]
            }
        except Exception as e:
            raise ValueError(f"Failed to generate summary: {str(e)}")

    @mcp.tool()
    def list_scheduled_dates(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[str]:
        """WHEN TO USE: When you need to see which dates have plans scheduled.

        Returns a list of dates that have workout plans. Useful for:
        - Checking what's already scheduled before adding new plans
        - Finding gaps in the training schedule
        - Planning around existing workouts

        Args:
            start_date: Start date (YYYY-MM-DD), defaults to today
            end_date: End date (YYYY-MM-DD), defaults to 6 weeks from today

        Returns:
            List of dates (YYYY-MM-DD) that have plans
        """
        try:
            if not start_date:
                start_date = date.today().isoformat()
            if not end_date:
                end_date = (date.today() + timedelta(weeks=6)).isoformat()

            query = """
                SELECT date FROM workout_plans
                WHERE date >= ? AND date <= ?
                ORDER BY date
            """
            results = db_manager.execute_query(query, [start_date, end_date])

            return [row["date"] for row in results]
        except Exception as e:
            raise ValueError(f"Failed to list scheduled dates: {str(e)}")

    @mcp.tool()
    def ingest_training_program(
        plans: Dict[str, Dict[str, Any]],
        transform_blocks: bool = True
    ) -> Dict[str, Any]:
        """WHEN TO USE: When loading a complete training program with multiple workout dates.

        Bulk ingests multiple workout plans at once. Accepts either:
        1. Block-based format (from LLM plan generation) - set transform_blocks=True
        2. Flat exercise format (ready for storage) - set transform_blocks=False

        Args:
            plans: Dictionary mapping dates (YYYY-MM-DD) to plan objects.
                   Block format includes: phase, theme, location, total_duration_min, blocks[]
                   Flat format includes: day_name, location, phase, exercises[]
            transform_blocks: If True, transforms block-based format to flat exercise list.
                            Set to False if plans are already in flat format.

        Returns:
            Summary of ingestion results with success/failure counts

        Example (block format):
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
                            "title": "Strength Block",
                            "rest_guidance": "Rest until HR <= 130",
                            "exercises": [
                                {"name": "KB Goblet Squat", "sets": 3, "reps": 10, "tempo": "3-1-1"}
                            ]
                        }
                    ]
                }
            })
        """
        results = {"success": [], "failed": [], "total": len(plans)}

        for date_str, plan_data in sorted(plans.items()):
            try:
                # Validate date format
                datetime.strptime(date_str, "%Y-%m-%d")

                # Transform if needed
                if transform_blocks and "blocks" in plan_data:
                    plan = _transform_block_plan(plan_data)
                else:
                    plan = plan_data

                # Validate required fields
                if "day_name" not in plan:
                    plan["day_name"] = plan_data.get("theme", "Workout")
                if "exercises" not in plan or not plan["exercises"]:
                    raise ValueError("Plan must have exercises")

                # Save to database
                now = get_utc_now()
                plan_json = json.dumps(plan)

                query = """
                    INSERT OR REPLACE INTO workout_plans (date, plan_json, last_modified, last_modified_by)
                    VALUES (?, ?, ?, ?)
                """
                db_manager.execute_write(query, [date_str, plan_json, now, "mcp"])
                results["success"].append(date_str)

            except Exception as e:
                results["failed"].append({"date": date_str, "error": str(e)})

        return {
            "message": f"Ingested {len(results['success'])} of {results['total']} plans",
            "success_count": len(results["success"]),
            "failed_count": len(results["failed"]),
            "success_dates": results["success"],
            "failed": results["failed"]
        }

    @mcp.tool()
    def update_exercise(
        date: str,
        exercise_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """WHEN TO USE: When modifying a specific exercise within an existing plan.

        Updates fields of a specific exercise without replacing the entire plan.
        Useful for tweaking sets, reps, weights, or guidance notes.

        Args:
            date: Date of the plan (YYYY-MM-DD)
            exercise_id: ID of the exercise to update
            updates: Dictionary of fields to update. Can include:
                     - name, type, target_sets, target_reps, target_duration_min
                     - guidance_note, items, load_guide, tempo, notes

        Returns:
            Updated exercise and confirmation

        Example:
            update_exercise("2026-02-02", "ex_1", {
                "target_sets": 4,
                "target_reps": "8",
                "guidance_note": "Increase weight by 5kg"
            })
        """
        try:
            # Get existing plan
            query = "SELECT plan_json FROM workout_plans WHERE date = ?"
            results = db_manager.execute_query(query, [date])

            if not results:
                raise ValueError(f"No plan found for date: {date}")

            plan = json.loads(results[0]["plan_json"])

            # Find and update the exercise
            exercise_found = False
            for exercise in plan.get("exercises", []):
                if exercise.get("id") == exercise_id:
                    exercise.update(updates)
                    exercise_found = True
                    updated_exercise = exercise
                    break

            if not exercise_found:
                raise ValueError(f"Exercise '{exercise_id}' not found in plan for {date}")

            # Save updated plan
            now = get_utc_now()
            plan_json = json.dumps(plan)

            update_query = """
                UPDATE workout_plans
                SET plan_json = ?, last_modified = ?, last_modified_by = ?
                WHERE date = ?
            """
            db_manager.execute_write(update_query, [plan_json, now, "mcp", date])

            return {
                "success": True,
                "date": date,
                "exercise_id": exercise_id,
                "updated_exercise": updated_exercise,
                "message": f"Exercise '{exercise_id}' updated successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to update exercise: {str(e)}")

    @mcp.tool()
    def add_exercise(
        date: str,
        exercise: Dict[str, Any],
        position: Optional[int] = None
    ) -> Dict[str, Any]:
        """WHEN TO USE: When adding a new exercise to an existing workout plan.

        Adds a new exercise to a plan at the specified position.

        Args:
            date: Date of the plan (YYYY-MM-DD)
            exercise: Exercise object with required fields (id, name, type)
            position: Index to insert at (0 = beginning). None = append to end.

        Returns:
            Confirmation with updated exercise count

        Example:
            add_exercise("2026-02-02", {
                "id": "ex_new",
                "name": "Plank Hold",
                "type": "duration",
                "target_duration_min": 1,
                "guidance_note": "Maintain tight core"
            }, position=5)
        """
        # Validate exercise
        required = ["id", "name", "type"]
        for field in required:
            if field not in exercise:
                raise ValueError(f"Exercise missing required field: {field}")

        valid_types = ["strength", "duration", "checklist", "weighted_time", "interval", "circuit"]
        if exercise["type"] not in valid_types:
            raise ValueError(f"Invalid exercise type: {exercise['type']}")

        try:
            # Get existing plan
            query = "SELECT plan_json FROM workout_plans WHERE date = ?"
            results = db_manager.execute_query(query, [date])

            if not results:
                raise ValueError(f"No plan found for date: {date}")

            plan = json.loads(results[0]["plan_json"])

            # Check for duplicate ID
            existing_ids = {ex.get("id") for ex in plan.get("exercises", [])}
            if exercise["id"] in existing_ids:
                raise ValueError(f"Exercise ID '{exercise['id']}' already exists in plan")

            # Add exercise at position
            exercises = plan.get("exercises", [])
            if position is None:
                exercises.append(exercise)
            else:
                exercises.insert(position, exercise)
            plan["exercises"] = exercises

            # Save updated plan
            now = get_utc_now()
            plan_json = json.dumps(plan)

            update_query = """
                UPDATE workout_plans
                SET plan_json = ?, last_modified = ?, last_modified_by = ?
                WHERE date = ?
            """
            db_manager.execute_write(update_query, [plan_json, now, "mcp", date])

            return {
                "success": True,
                "date": date,
                "added_exercise": exercise,
                "total_exercises": len(exercises),
                "message": f"Exercise '{exercise['id']}' added successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to add exercise: {str(e)}")

    @mcp.tool()
    def remove_exercise(
        date: str,
        exercise_id: str
    ) -> Dict[str, Any]:
        """WHEN TO USE: When removing an exercise from an existing workout plan.

        Removes an exercise by ID from the specified plan.

        Args:
            date: Date of the plan (YYYY-MM-DD)
            exercise_id: ID of the exercise to remove

        Returns:
            Confirmation with updated exercise count

        Example:
            remove_exercise("2026-02-02", "ex_3")
        """
        try:
            # Get existing plan
            query = "SELECT plan_json FROM workout_plans WHERE date = ?"
            results = db_manager.execute_query(query, [date])

            if not results:
                raise ValueError(f"No plan found for date: {date}")

            plan = json.loads(results[0]["plan_json"])

            # Find and remove the exercise
            exercises = plan.get("exercises", [])
            original_count = len(exercises)
            exercises = [ex for ex in exercises if ex.get("id") != exercise_id]

            if len(exercises) == original_count:
                raise ValueError(f"Exercise '{exercise_id}' not found in plan for {date}")

            plan["exercises"] = exercises

            # Save updated plan
            now = get_utc_now()
            plan_json = json.dumps(plan)

            update_query = """
                UPDATE workout_plans
                SET plan_json = ?, last_modified = ?, last_modified_by = ?
                WHERE date = ?
            """
            db_manager.execute_write(update_query, [plan_json, now, "mcp", date])

            return {
                "success": True,
                "date": date,
                "removed_exercise_id": exercise_id,
                "remaining_exercises": len(exercises),
                "message": f"Exercise '{exercise_id}' removed successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to remove exercise: {str(e)}")

    @mcp.tool()
    def delete_workout_plan(date: str) -> Dict[str, Any]:
        """WHEN TO USE: When removing a workout plan entirely for a specific date.

        Deletes the entire workout plan for the specified date.

        Args:
            date: Date of the plan to delete (YYYY-MM-DD)

        Returns:
            Confirmation of deletion

        Example:
            delete_workout_plan("2026-02-02")
        """
        try:
            # Validate date format
            datetime.strptime(date, "%Y-%m-%d")

            # Check if plan exists
            check_query = "SELECT date FROM workout_plans WHERE date = ?"
            results = db_manager.execute_query(check_query, [date])

            if not results:
                raise ValueError(f"No plan found for date: {date}")

            # Delete the plan
            delete_query = "DELETE FROM workout_plans WHERE date = ?"
            db_manager.execute_write(delete_query, [date])

            return {
                "success": True,
                "date": date,
                "message": f"Workout plan for {date} deleted successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to delete workout plan: {str(e)}")

    @mcp.tool()
    def update_plan_metadata(
        date: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """WHEN TO USE: When updating plan metadata without changing exercises.

        Updates plan-level fields like day_name, location, phase without
        modifying the exercises list.

        Args:
            date: Date of the plan (YYYY-MM-DD)
            updates: Fields to update. Can include:
                     - day_name: New workout name/theme
                     - location: "Home" or "Gym"
                     - phase: "Foundation", "Building", or "Intensity"
                     - total_duration_min: Expected workout duration

        Returns:
            Updated plan metadata

        Example:
            update_plan_metadata("2026-02-02", {
                "day_name": "Lower Body Focus",
                "phase": "Building"
            })
        """
        allowed_fields = {"day_name", "location", "phase", "total_duration_min"}
        invalid_fields = set(updates.keys()) - allowed_fields
        if invalid_fields:
            raise ValueError(f"Invalid metadata fields: {invalid_fields}. Allowed: {allowed_fields}")

        try:
            # Get existing plan
            query = "SELECT plan_json FROM workout_plans WHERE date = ?"
            results = db_manager.execute_query(query, [date])

            if not results:
                raise ValueError(f"No plan found for date: {date}")

            plan = json.loads(results[0]["plan_json"])

            # Update metadata fields
            plan.update(updates)

            # Save updated plan
            now = get_utc_now()
            plan_json = json.dumps(plan)

            update_query = """
                UPDATE workout_plans
                SET plan_json = ?, last_modified = ?, last_modified_by = ?
                WHERE date = ?
            """
            db_manager.execute_write(update_query, [plan_json, now, "mcp", date])

            return {
                "success": True,
                "date": date,
                "updated_fields": list(updates.keys()),
                "plan_metadata": {
                    "day_name": plan.get("day_name"),
                    "location": plan.get("location"),
                    "phase": plan.get("phase"),
                    "total_duration_min": plan.get("total_duration_min"),
                    "exercise_count": len(plan.get("exercises", []))
                },
                "message": f"Plan metadata updated successfully"
            }
        except Exception as e:
            raise ValueError(f"Failed to update plan metadata: {str(e)}")

    @mcp.resource("file://coach_plan_guide")
    def coach_plan_guide() -> str:
        """Complete guide to creating workout plans."""
        return _get_coach_plan_guide()

    return mcp


def _is_bodyweight_or_band(name: str) -> bool:
    """Check if an exercise is bodyweight or band-based (no meaningful weight)."""
    keywords = [
        "push-up", "pushup", "push up", "bodyweight", "band pull",
        "banded", "jump squat", "plank", "dead hang", "wall sit",
        "glute bridge",
    ]
    lower = name.lower()
    return any(kw in lower for kw in keywords)


def _transform_block_to_exercises(block: dict, block_index: int) -> list:
    """Transform a block into a list of exercises with proper IDs and types."""
    exercises = []
    block_type = block.get("block_type", "")
    title = block.get("title", "")
    rest_guidance = block.get("rest_guidance", "")
    duration = block.get("duration_min", 0)

    # Handle warmup blocks specially - aggregate into single checklist
    if block_type == "warmup" and "exercises" in block:
        items = []
        for ex in block["exercises"]:
            name = ex.get("name", "Unknown")
            reps = ex.get("reps", "")
            if reps:
                items.append(f"{name} x{reps}" if isinstance(reps, int) else f"{name} {reps}")
            else:
                items.append(name)

        exercise = {
            "id": f"warmup_{block_index}",
            "name": title or "Warmup",
            "type": "checklist",
            "items": items
        }
        exercises.append(exercise)

    # Handle blocks with exercises list (non-warmup)
    elif "exercises" in block:
        block_rounds = block.get("rounds")

        for i, ex in enumerate(block["exercises"]):
            exercise_id = f"{block_type}_{block_index}_{i+1}"

            # Determine exercise type based on block type
            if block_type in ["circuit", "power"]:
                ex_type = "circuit"
            elif block_type in ["strength", "accessory"]:
                ex_type = "strength"
            else:
                ex_type = "strength"

            exercise = {
                "id": exercise_id,
                "name": ex.get("name", "Unknown"),
                "type": ex_type,
            }

            if ex.get("sets"):
                exercise["target_sets"] = ex["sets"] if isinstance(ex["sets"], int) else 3
            elif block_rounds:
                exercise["target_sets"] = block_rounds
            if ex.get("reps"):
                reps_str = str(ex["reps"])
                exercise["target_reps"] = reps_str
                if "sec" in reps_str.lower():
                    exercise["show_time"] = True

            # Hide weight for bodyweight/band exercises
            equipment = ex.get("equipment")
            if equipment:
                if equipment in ("bodyweight", "band"):
                    exercise["hide_weight"] = True
            elif _is_bodyweight_or_band(ex.get("name", "")):
                exercise["hide_weight"] = True

            # Build guidance note
            notes = []
            if ex.get("tempo"):
                notes.append(f"Tempo {ex['tempo']}")
            if ex.get("load_guide"):
                notes.append(ex["load_guide"])
            if ex.get("notes"):
                notes.append(ex["notes"])
            if rest_guidance and block_type == "strength":
                notes.append(rest_guidance)

            if notes:
                exercise["guidance_note"] = ". ".join(notes)

            exercises.append(exercise)

    # Handle blocks with instructions (cardio blocks)
    elif "instructions" in block:
        exercise_id = f"{block_type}_{block_index}_1"
        instructions_text = " ".join(block["instructions"])

        if "VO2" in instructions_text or "HARD" in instructions_text:
            ex_type = "interval"
            name = "VO2 Max Intervals"
        else:
            ex_type = "duration"
            name = title or "Zone 2 Cardio"

        exercise = {
            "id": exercise_id,
            "name": name,
            "type": ex_type,
            "target_duration_min": duration,
            "guidance_note": " | ".join(block["instructions"])
        }
        exercises.append(exercise)

    return exercises


def _transform_block_plan(plan_data: dict) -> dict:
    """Transform block-based plan to include both blocks and flat exercise list."""
    blocks = []
    exercises = []  # Keep for backward compatibility with logs

    for i, block in enumerate(plan_data.get("blocks", [])):
        block_exercises = _transform_block_to_exercises(block, i)
        exercises.extend(block_exercises)

        transformed_block = {
            "block_index": i,
            "block_type": block.get("block_type", ""),
            "title": block.get("title", ""),
            "duration_min": block.get("duration_min"),
            "rest_guidance": block.get("rest_guidance", ""),
            "rounds": block.get("rounds"),
            "exercises": block_exercises
        }
        blocks.append(transformed_block)

    return {
        "day_name": plan_data.get("theme", "Workout"),
        "location": plan_data.get("location", "Home"),
        "phase": plan_data.get("phase", "Foundation"),
        "total_duration_min": plan_data.get("total_duration_min", 60),
        "blocks": blocks,
        "exercises": exercises
    }


def _get_coach_plan_guide() -> str:
    """Get comprehensive guide for creating workout plans."""
    return """
# Coach Workout Plan Guide

## Quick Start
1. Use `list_scheduled_dates` to see what's already planned
2. Use `get_workout_plan` to see existing plan structures
3. Use `set_workout_plan` to create new plans
4. Use `get_workout_logs` to analyze past performance

## Plan Structure

Each workout plan has:
- `day_name`: Description of the workout focus (e.g., "Lower Body + Bike")
- `location`: "Home" or "Gym"
- `phase`: Training phase ("Foundation", "Building", "Intensity")
- `exercises`: Array of exercise definitions

## Exercise Types

### strength
For weight training exercises with sets/reps.
```json
{
    "id": "ex_1",
    "name": "KB Goblet Squat",
    "type": "strength",
    "target_sets": 3,
    "target_reps": "10",
    "guidance_note": "Tempo 3-1-1. Rest until HR <= 130."
}
```

### duration
For cardio with time-based goals.
```json
{
    "id": "cardio_1",
    "name": "Zone 2 Bike",
    "type": "duration",
    "target_duration_min": 15,
    "guidance_note": "HR 135-148. Log Avg/Max HR."
}
```

### checklist
For warm-ups or routines with multiple items.
```json
{
    "id": "warmup_1",
    "name": "Stability Start",
    "type": "checklist",
    "items": ["Cat-Cow x10", "Bird-Dog x5/side", "Dead Bug x10"]
}
```

### weighted_time
For exercises with weight and duration (e.g., carries).
```json
{
    "id": "ex_5",
    "name": "Farmer's Carry",
    "type": "weighted_time",
    "target_duration_sec": 60,
    "guidance_note": "Heavy weight, maintain posture"
}
```

### interval
For HIIT or interval training.
```json
{
    "id": "hiit_1",
    "name": "Bike Intervals",
    "type": "interval",
    "rounds": 4,
    "work_duration_sec": 30,
    "rest_duration_sec": 90,
    "guidance_note": "All-out effort on work intervals"
}
```

## Best Practices

1. **Unique IDs**: Each exercise needs a unique `id` within the plan
2. **Guidance Notes**: Include tempo, rest periods, HR targets
3. **Progressive Overload**: Increase volume/intensity across phases
4. **Rest Guidance**: Include HR-based rest recommendations for strength work

## Example: Full Workout Plan

```json
{
    "day_name": "Lower Body + Conditioning",
    "location": "Home",
    "phase": "Foundation",
    "exercises": [
        {
            "id": "warmup_1",
            "name": "Stability Start",
            "type": "checklist",
            "items": [
                "Cat-Cow x10",
                "Bird-Dog x5/side",
                "Dead Bug x10",
                "Single-Leg Balance 30s/side"
            ]
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
            "id": "ex_2",
            "name": "DB Romanian Deadlift",
            "type": "strength",
            "target_sets": 3,
            "target_reps": "10",
            "guidance_note": "Tempo 3-1-1. Feel hamstring stretch."
        },
        {
            "id": "cardio_1",
            "name": "Zone 2 Bike",
            "type": "duration",
            "target_duration_min": 15,
            "guidance_note": "HR 135-148. Log Avg/Max HR."
        }
    ]
}
```
    """.strip()


def main():
    """Main entry point for the Coach MCP server."""
    try:
        mcp = create_mcp_server()
        mcp.run()
    except Exception as e:
        print(f"Failed to start MCP server: {e}")
        raise


if __name__ == "__main__":
    main()
