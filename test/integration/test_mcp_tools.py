"""Integration tests for MCP tools."""

import json
import pytest
import sqlite3
from datetime import datetime, timedelta, timezone


@pytest.mark.integration
class TestMCPConfig:
    def test_config_from_db_path(self, temp_db_path):
        """Should create config from database path."""
        from coach_mcp.config import MCPConfig

        # Create db first
        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig.from_db_path(temp_db_path)
        assert config.db_path == temp_db_path
        assert config.max_rows == 1000

    def test_config_validation_missing_db(self, tmp_path):
        """Should raise error for missing database."""
        from coach_mcp.config import MCPConfig

        config = MCPConfig(db_path=tmp_path / "nonexistent.db")
        with pytest.raises(ValueError, match="Database file not found"):
            config.validate()

    def test_config_validation_invalid_max_rows(self, temp_db_path):
        """Should raise error for invalid max_rows."""
        from coach_mcp.config import MCPConfig

        # Create db first
        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig(db_path=temp_db_path, max_rows=0)
        with pytest.raises(ValueError, match="max_rows must be at least 1"):
            config.validate()

    def test_config_validation_max_rows_exceeds_absolute(self, temp_db_path):
        """Should raise error when max_rows exceeds absolute limit."""
        from coach_mcp.config import MCPConfig

        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig(db_path=temp_db_path, max_rows=10000, max_rows_absolute=5000)
        with pytest.raises(ValueError, match="cannot exceed"):
            config.validate()

    def test_config_validation_db_path_is_directory(self, tmp_path):
        """Should raise error when db_path is a directory, not a file."""
        from coach_mcp.config import MCPConfig

        config = MCPConfig(db_path=tmp_path)
        with pytest.raises(ValueError, match="not a file"):
            config.validate()

    def test_config_validation_invalid_transport(self, temp_db_path):
        """Should raise error for invalid transport."""
        from coach_mcp.config import MCPConfig

        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig(db_path=temp_db_path, transport="invalid")
        with pytest.raises(ValueError, match="Invalid transport"):
            config.validate()

    def test_config_validation_invalid_port(self, temp_db_path):
        """Should raise error for invalid port."""
        from coach_mcp.config import MCPConfig

        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig(db_path=temp_db_path, port=0)
        with pytest.raises(ValueError, match="Invalid port"):
            config.validate()

    def test_config_validation_port_too_high(self, temp_db_path):
        """Should raise error for port above 65535."""
        from coach_mcp.config import MCPConfig

        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE TABLE test (id TEXT)")
        conn.close()

        config = MCPConfig(db_path=temp_db_path, port=70000)
        with pytest.raises(ValueError, match="Invalid port"):
            config.validate()


@pytest.mark.integration
class TestDatabaseManager:
    def test_read_only_connection(self, mcp_config, db_manager):
        """Read-only connection should not allow writes."""
        # This should work (read)
        result = db_manager.execute_query("SELECT 1 as value", read_only=True)
        assert result[0]["value"] == 1

    def test_write_connection(self, mcp_config, db_manager):
        """Write connection should allow writes."""
        # Insert data
        db_manager.execute_write(
            "INSERT INTO workout_plans (date, plan_json, last_modified) VALUES (?, ?, ?)",
            ["2026-02-02", '{"test": true}', "2026-01-30T00:00:00Z"]
        )

        # Verify
        result = db_manager.execute_query("SELECT date FROM workout_plans")
        assert len(result) == 1
        assert result[0]["date"] == "2026-02-02"

    def test_execute_query_with_write_mode(self, mcp_config, db_manager):
        """execute_query with read_only=False should commit changes."""
        # Insert using execute_query with read_only=False
        db_manager.execute_query(
            "INSERT INTO workout_plans (date, plan_json, last_modified) VALUES (?, ?, ?)",
            ["2026-03-01", '{"test": true}', "2026-01-30T00:00:00Z"],
            read_only=False
        )

        # Verify the insert was committed
        result = db_manager.execute_query("SELECT date FROM workout_plans WHERE date = '2026-03-01'")
        assert len(result) == 1

    def test_execute_query_sql_error(self, mcp_config, db_manager):
        """execute_query should raise ValueError on SQL error."""
        with pytest.raises(ValueError, match="Database error"):
            db_manager.execute_query("SELECT * FROM nonexistent_table")

    def test_execute_write_sql_error(self, mcp_config, db_manager):
        """execute_write should raise ValueError on SQL error."""
        with pytest.raises(ValueError, match="Database error"):
            db_manager.execute_write("INSERT INTO nonexistent_table (x) VALUES (?)", ["test"])


@pytest.mark.integration
class TestSetWorkoutPlan:
    def test_create_plan(self, mcp_config, sample_plan):
        """Should create a new workout plan."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Call set_workout_plan
        result = tools["set_workout_plan"].fn(
            date="2026-02-02",
            plan=sample_plan
        )

        assert result["success"] is True
        assert result["date"] == "2026-02-02"
        assert result["plan"]["day_name"] == "Test Workout"

    def test_update_existing_plan(self, mcp_config, sample_plan):
        """Should update an existing plan."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plan
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        # Update plan
        updated_plan = {**sample_plan, "day_name": "Updated Workout"}
        result = tools["set_workout_plan"].fn(date="2026-02-02", plan=updated_plan)

        assert result["success"] is True
        assert result["plan"]["day_name"] == "Updated Workout"

    def test_plan_validation_missing_exercises(self, mcp_config):
        """Should reject plan without exercises or blocks."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {"day_name": "Test"}  # Missing exercises and blocks

        with pytest.raises(ValueError, match="must have either 'exercises' or 'blocks'"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_invalid_date(self, mcp_config, sample_plan):
        """Should reject invalid date format."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="Invalid date format"):
            tools["set_workout_plan"].fn(date="02-02-2026", plan=sample_plan)

    def test_plan_validation_exercise_missing_id(self, mcp_config):
        """Should reject exercise without id."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "exercises": [{"name": "Squat", "type": "strength"}]  # Missing id
        }

        with pytest.raises(ValueError, match="missing 'id' field"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_invalid_exercise_type(self, mcp_config):
        """Should reject invalid exercise type."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "exercises": [{"id": "ex_1", "name": "Squat", "type": "invalid_type"}]
        }

        with pytest.raises(ValueError, match="invalid type"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_plan_not_a_dict(self, mcp_config):
        """Should reject plan that is not a dictionary."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="Plan must be a dictionary"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan="not a dict")

    def test_plan_validation_exercises_not_a_list(self, mcp_config):
        """Should reject plan where exercises is not a list."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "exercises": "not a list"
        }

        with pytest.raises(ValueError, match="exercises must be a list"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_exercise_missing_name(self, mcp_config):
        """Should reject exercise without name."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "exercises": [{"id": "ex_1", "type": "strength"}]  # Missing name
        }

        with pytest.raises(ValueError, match="missing 'name' field"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_exercise_missing_type(self, mcp_config):
        """Should reject exercise without type."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "exercises": [{"id": "ex_1", "name": "Squat"}]  # Missing type
        }

        with pytest.raises(ValueError, match="missing 'type' field"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_create_plan_with_blocks(self, mcp_config):
        """Should transform blocks into exercises and store both."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        block_plan = {
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
                        {"name": "Bench Press", "sets": 4, "reps": "6-8"},
                        {"name": "Barbell Row", "sets": 4, "reps": "6-8"}
                    ]
                },
                {
                    "block_type": "cardio",
                    "title": "Zone 2 Cooldown",
                    "duration_min": 10,
                    "instructions": ["Easy pace on bike for 10 minutes"]
                }
            ]
        }

        result = tools["set_workout_plan"].fn(date="2026-02-10", plan=block_plan)

        assert result["success"] is True
        saved_plan = result["plan"]
        # Exercises list should be generated from blocks
        assert "exercises" in saved_plan
        assert len(saved_plan["exercises"]) > 0
        # Blocks should be preserved (transformed)
        assert "blocks" in saved_plan
        assert len(saved_plan["blocks"]) == 3
        # Verify exercises have required fields
        for ex in saved_plan["exercises"]:
            assert "id" in ex
            assert "name" in ex
            assert "type" in ex

        # Verify we can retrieve the stored plan
        get_result = tools["get_workout_plan"].fn(
            start_date="2026-02-10", end_date="2026-02-10"
        )
        assert len(get_result) == 1

    def test_create_plan_with_blocks_and_exercises(self, mcp_config):
        """Should store as-is when both blocks and exercises are provided."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plan = {
            "day_name": "Pre-built Plan",
            "blocks": [
                {
                    "block_index": 0,
                    "block_type": "strength",
                    "title": "Main Lifts",
                    "exercises": [
                        {"id": "strength_0_1", "name": "Squat", "type": "strength",
                         "target_sets": 3, "target_reps": "8"}
                    ]
                }
            ],
            "exercises": [
                {"id": "strength_0_1", "name": "Squat", "type": "strength",
                 "target_sets": 3, "target_reps": "8"}
            ]
        }

        result = tools["set_workout_plan"].fn(date="2026-02-11", plan=plan)

        assert result["success"] is True
        saved_plan = result["plan"]
        # Should be stored as-is, no transform
        assert saved_plan["exercises"] == plan["exercises"]
        assert saved_plan["blocks"] == plan["blocks"]

    def test_plan_validation_no_exercises_no_blocks(self, mcp_config):
        """Should reject plan with neither exercises nor blocks."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {"day_name": "Test", "location": "Gym"}

        with pytest.raises(ValueError, match="must have either 'exercises' or 'blocks'"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_blocks_not_a_list(self, mcp_config):
        """Should reject plan where blocks is not a list."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "blocks": "not a list"
        }

        with pytest.raises(ValueError, match="blocks must be a list"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)

    def test_plan_validation_block_missing_type(self, mcp_config):
        """Should reject block without block_type."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        invalid_plan = {
            "day_name": "Test",
            "blocks": [
                {"title": "Warmup", "exercises": [{"name": "Stretch"}]}
            ]
        }

        with pytest.raises(ValueError, match="missing 'block_type' field"):
            tools["set_workout_plan"].fn(date="2026-02-02", plan=invalid_plan)


@pytest.mark.integration
class TestGetWorkoutPlan:
    def test_get_plans_empty(self, mcp_config):
        """Should return empty list for no plans."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        result = tools["get_workout_plan"].fn(
            start_date="2026-02-01",
            end_date="2026-02-28"
        )

        assert result == []

    def test_get_plans_with_data(self, mcp_config, sample_plan):
        """Should return plans within date range."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plans
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        tools["set_workout_plan"].fn(
            date="2026-02-04",
            plan={**sample_plan, "day_name": "Wednesday Workout"}
        )

        result = tools["get_workout_plan"].fn(
            start_date="2026-02-01",
            end_date="2026-02-05"
        )

        assert len(result) == 2
        dates = [p["date"] for p in result]
        assert "2026-02-02" in dates
        assert "2026-02-04" in dates

    def test_get_plans_date_filtering(self, mcp_config, sample_plan):
        """Should only return plans within specified range."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plans
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        tools["set_workout_plan"].fn(date="2026-02-09", plan=sample_plan)

        # Only request first week
        result = tools["get_workout_plan"].fn(
            start_date="2026-02-01",
            end_date="2026-02-07"
        )

        assert len(result) == 1
        assert result[0]["date"] == "2026-02-02"


@pytest.mark.integration
class TestGetWorkoutLogs:
    def test_get_logs_empty(self, mcp_config):
        """Should return empty list for no logs."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        result = tools["get_workout_logs"].fn(
            start_date="2026-02-01",
            end_date="2026-02-28"
        )

        assert result == []

    def test_get_logs_with_data(self, mcp_config, sample_log):
        """Should return logs within date range."""
        from coach_mcp.server import create_mcp_server, DatabaseManager

        db_manager = DatabaseManager(mcp_config)
        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Insert log directly
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        db_manager.execute_write(
            "INSERT INTO workout_logs (date, log_json, last_modified) VALUES (?, ?, ?)",
            ["2026-02-02", json.dumps(sample_log), now]
        )

        result = tools["get_workout_logs"].fn(
            start_date="2026-02-01",
            end_date="2026-02-05"
        )

        assert len(result) == 1
        assert result[0]["date"] == "2026-02-02"
        assert result[0]["log"]["session_feedback"]["pain_discomfort"] == "None"


@pytest.mark.integration
class TestGetWorkoutSummary:
    def test_summary_empty_database(self, mcp_config):
        """Should return summary with zero counts for empty database."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        result = tools["get_workout_summary"].fn(days=30)

        assert result["planned_workouts"] == 0
        assert result["completed_workouts"] == 0
        assert result["completion_rate_percent"] == 0

    def test_summary_days_exceeds_max(self, mcp_config):
        """Should raise ValueError when days exceeds 365."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="Days cannot exceed 365"):
            tools["get_workout_summary"].fn(days=400)

    def test_summary_with_data(self, mcp_config, sample_plan, sample_log):
        """Should return accurate summary with data."""
        from coach_mcp.server import create_mcp_server, DatabaseManager

        db_manager = DatabaseManager(mcp_config)
        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Insert plan and log
        db_manager.execute_write(
            "INSERT INTO workout_plans (date, plan_json, last_modified) VALUES (?, ?, ?)",
            [today, json.dumps(sample_plan), now]
        )
        db_manager.execute_write(
            "INSERT INTO workout_logs (date, log_json, last_modified) VALUES (?, ?, ?)",
            [today, json.dumps(sample_log), now]
        )

        result = tools["get_workout_summary"].fn(days=30)

        assert result["planned_workouts"] == 1
        assert result["completed_workouts"] == 1
        assert result["completion_rate_percent"] == 100.0


@pytest.mark.integration
class TestListScheduledDates:
    def test_list_empty(self, mcp_config):
        """Should return empty list when no plans exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        result = tools["list_scheduled_dates"].fn()
        assert result == []

    def test_list_with_plans(self, mcp_config, sample_plan):
        """Should return dates with scheduled plans."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plans
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        tools["set_workout_plan"].fn(date="2026-02-04", plan=sample_plan)
        tools["set_workout_plan"].fn(date="2026-02-06", plan=sample_plan)

        result = tools["list_scheduled_dates"].fn(
            start_date="2026-02-01",
            end_date="2026-02-28"
        )

        assert len(result) == 3
        assert "2026-02-02" in result
        assert "2026-02-04" in result
        assert "2026-02-06" in result

    def test_list_respects_date_range(self, mcp_config, sample_plan):
        """Should only return dates within specified range."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plans in different weeks
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        tools["set_workout_plan"].fn(date="2026-03-02", plan=sample_plan)

        result = tools["list_scheduled_dates"].fn(
            start_date="2026-02-01",
            end_date="2026-02-28"
        )

        assert len(result) == 1
        assert "2026-02-02" in result
        assert "2026-03-02" not in result


@pytest.mark.integration
class TestIngestTrainingProgram:
    def test_ingest_multiple_plans(self, mcp_config):
        """Should ingest multiple plans at once."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plans = {
            "2026-02-02": {
                "day_name": "Monday Workout",
                "location": "Home",
                "phase": "Foundation",
                "exercises": [
                    {"id": "ex_1", "name": "Squat", "type": "strength", "target_sets": 3, "target_reps": "10"}
                ]
            },
            "2026-02-04": {
                "day_name": "Wednesday Workout",
                "location": "Gym",
                "phase": "Foundation",
                "exercises": [
                    {"id": "ex_1", "name": "Deadlift", "type": "strength", "target_sets": 4, "target_reps": "5"}
                ]
            }
        }

        result = tools["ingest_training_program"].fn(plans=plans, transform_blocks=False)

        assert result["success_count"] == 2
        assert result["failed_count"] == 0
        assert "2026-02-02" in result["success_dates"]
        assert "2026-02-04" in result["success_dates"]

    def test_ingest_with_block_transform(self, mcp_config):
        """Should transform block-based format to flat exercises."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plans = {
            "2026-02-02": {
                "phase": "Foundation",
                "theme": "Lower Body + Bike",
                "location": "Home",
                "total_duration_min": 60,
                "blocks": [
                    {
                        "block_type": "warmup",
                        "title": "Warmup",
                        "exercises": [
                            {"name": "Cat-Cow", "reps": 10}
                        ]
                    },
                    {
                        "block_type": "strength",
                        "title": "Strength",
                        "exercises": [
                            {"name": "Squat", "sets": 3, "reps": 10}
                        ]
                    }
                ]
            }
        }

        result = tools["ingest_training_program"].fn(plans=plans, transform_blocks=True)
        assert result["success_count"] == 1

        # Verify transformed plan
        fetched = tools["get_workout_plan"].fn(start_date="2026-02-02", end_date="2026-02-02")
        assert len(fetched) == 1
        plan = fetched[0]["plan"]
        assert plan["day_name"] == "Lower Body + Bike"
        assert len(plan["exercises"]) == 2

    def test_ingest_partial_failure(self, mcp_config):
        """Should report partial failures."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plans = {
            "2026-02-02": {
                "day_name": "Valid Plan",
                "exercises": [{"id": "ex_1", "name": "Squat", "type": "strength"}]
            },
            "invalid-date": {
                "day_name": "Invalid Date Plan",
                "exercises": [{"id": "ex_1", "name": "Squat", "type": "strength"}]
            }
        }

        result = tools["ingest_training_program"].fn(plans=plans, transform_blocks=False)

        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert "2026-02-02" in result["success_dates"]

    def test_ingest_without_transform_adds_day_name(self, mcp_config):
        """Should auto-set day_name from theme when missing and not transforming."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plans = {
            "2026-02-02": {
                "theme": "Upper Body Focus",
                "exercises": [{"id": "ex_1", "name": "Squat", "type": "strength"}]
            }
        }

        result = tools["ingest_training_program"].fn(plans=plans, transform_blocks=False)
        assert result["success_count"] == 1

        fetched = tools["get_workout_plan"].fn(start_date="2026-02-02", end_date="2026-02-02")
        assert fetched[0]["plan"]["day_name"] == "Upper Body Focus"

    def test_ingest_empty_exercises_fails(self, mcp_config):
        """Should fail when plan has no exercises."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        plans = {
            "2026-02-02": {
                "day_name": "Empty Plan",
                "exercises": []
            }
        }

        result = tools["ingest_training_program"].fn(plans=plans, transform_blocks=False)
        assert result["failed_count"] == 1
        assert result["success_count"] == 0


@pytest.mark.integration
class TestUpdateExercise:
    def test_update_exercise_fields(self, mcp_config, sample_plan):
        """Should update specific exercise fields."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        # Create plan
        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        # Update exercise
        result = tools["update_exercise"].fn(
            date="2026-02-02",
            exercise_id="ex_1",
            updates={"target_sets": 4, "target_reps": "8", "guidance_note": "Go heavier"}
        )

        assert result["success"] is True
        assert result["updated_exercise"]["target_sets"] == 4
        assert result["updated_exercise"]["target_reps"] == "8"
        assert result["updated_exercise"]["guidance_note"] == "Go heavier"

    def test_update_nonexistent_exercise(self, mcp_config, sample_plan):
        """Should fail when exercise not found."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="not found"):
            tools["update_exercise"].fn(
                date="2026-02-02",
                exercise_id="nonexistent",
                updates={"target_sets": 5}
            )

    def test_update_exercise_no_plan(self, mcp_config):
        """Should fail when plan doesn't exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="No plan found"):
            tools["update_exercise"].fn(
                date="2026-02-02",
                exercise_id="ex_1",
                updates={"target_sets": 5}
            )


@pytest.mark.integration
class TestAddExercise:
    def test_add_exercise_to_end(self, mcp_config, sample_plan):
        """Should add exercise to end of list."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        original_count = len(sample_plan["exercises"])

        result = tools["add_exercise"].fn(
            date="2026-02-02",
            exercise={
                "id": "ex_new",
                "name": "Plank",
                "type": "duration",
                "target_duration_min": 1
            }
        )

        assert result["success"] is True
        assert result["total_exercises"] == original_count + 1

    def test_add_exercise_at_position(self, mcp_config, sample_plan):
        """Should add exercise at specified position."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        tools["add_exercise"].fn(
            date="2026-02-02",
            exercise={"id": "ex_inserted", "name": "Inserted", "type": "strength"},
            position=1
        )

        # Verify position
        fetched = tools["get_workout_plan"].fn(start_date="2026-02-02", end_date="2026-02-02")
        exercises = fetched[0]["plan"]["exercises"]
        assert exercises[1]["id"] == "ex_inserted"

    def test_add_exercise_duplicate_id(self, mcp_config, sample_plan):
        """Should reject duplicate exercise ID."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="already exists"):
            tools["add_exercise"].fn(
                date="2026-02-02",
                exercise={"id": "ex_1", "name": "Duplicate", "type": "strength"}
            )

    def test_add_exercise_invalid_type(self, mcp_config, sample_plan):
        """Should reject invalid exercise type."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="Invalid exercise type"):
            tools["add_exercise"].fn(
                date="2026-02-02",
                exercise={"id": "ex_new", "name": "Invalid", "type": "invalid_type"}
            )

    def test_add_exercise_no_plan(self, mcp_config):
        """Should fail when plan doesn't exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="No plan found"):
            tools["add_exercise"].fn(
                date="2026-02-02",
                exercise={"id": "ex_new", "name": "Plank", "type": "duration"}
            )

    def test_add_exercise_missing_required_field(self, mcp_config, sample_plan):
        """Should reject exercise missing required fields."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="missing required field"):
            tools["add_exercise"].fn(
                date="2026-02-02",
                exercise={"name": "Plank", "type": "duration"}  # Missing id
            )


@pytest.mark.integration
class TestRemoveExercise:
    def test_remove_exercise(self, mcp_config, sample_plan):
        """Should remove exercise from plan."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        original_count = len(sample_plan["exercises"])

        result = tools["remove_exercise"].fn(date="2026-02-02", exercise_id="ex_1")

        assert result["success"] is True
        assert result["remaining_exercises"] == original_count - 1

    def test_remove_nonexistent_exercise(self, mcp_config, sample_plan):
        """Should fail when exercise not found."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="not found"):
            tools["remove_exercise"].fn(date="2026-02-02", exercise_id="nonexistent")

    def test_remove_exercise_no_plan(self, mcp_config):
        """Should fail when plan doesn't exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="No plan found"):
            tools["remove_exercise"].fn(date="2026-02-02", exercise_id="ex_1")


@pytest.mark.integration
class TestDeleteWorkoutPlan:
    def test_delete_plan(self, mcp_config, sample_plan):
        """Should delete workout plan."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        result = tools["delete_workout_plan"].fn(date="2026-02-02")
        assert result["success"] is True

        # Verify deletion
        fetched = tools["get_workout_plan"].fn(start_date="2026-02-02", end_date="2026-02-02")
        assert len(fetched) == 0

    def test_delete_nonexistent_plan(self, mcp_config):
        """Should fail when plan doesn't exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="No plan found"):
            tools["delete_workout_plan"].fn(date="2026-02-02")


@pytest.mark.integration
class TestUpdatePlanMetadata:
    def test_update_metadata(self, mcp_config, sample_plan):
        """Should update plan metadata without changing exercises."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)
        original_exercise_count = len(sample_plan["exercises"])

        result = tools["update_plan_metadata"].fn(
            date="2026-02-02",
            updates={"day_name": "Updated Name", "phase": "Building", "location": "Gym"}
        )

        assert result["success"] is True
        assert result["plan_metadata"]["day_name"] == "Updated Name"
        assert result["plan_metadata"]["phase"] == "Building"
        assert result["plan_metadata"]["location"] == "Gym"
        assert result["plan_metadata"]["exercise_count"] == original_exercise_count

    def test_update_metadata_no_plan(self, mcp_config):
        """Should fail when plan doesn't exist."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        with pytest.raises(ValueError, match="No plan found"):
            tools["update_plan_metadata"].fn(
                date="2026-02-02",
                updates={"day_name": "Updated"}
            )

    def test_update_metadata_invalid_field(self, mcp_config, sample_plan):
        """Should reject invalid metadata fields."""
        from coach_mcp.server import create_mcp_server

        mcp = create_mcp_server(mcp_config)
        tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}

        tools["set_workout_plan"].fn(date="2026-02-02", plan=sample_plan)

        with pytest.raises(ValueError, match="Invalid metadata fields"):
            tools["update_plan_metadata"].fn(
                date="2026-02-02",
                updates={"exercises": [], "invalid_field": "value"}
            )


@pytest.mark.integration
class TestMCPServerCreation:
    def test_create_server_from_env_var(self, temp_db_path, monkeypatch):
        """Should create server using COACH_DB_PATH env var."""
        import sqlite3
        from coach_mcp.server import create_mcp_server

        # Create database with required tables
        conn = sqlite3.connect(temp_db_path)
        conn.execute("""
            CREATE TABLE workout_plans (
                date TEXT PRIMARY KEY,
                plan_json TEXT NOT NULL,
                last_modified TEXT NOT NULL,
                last_modified_by TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE workout_logs (
                date TEXT PRIMARY KEY,
                log_json TEXT NOT NULL,
                last_modified TEXT NOT NULL,
                last_modified_by TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Set environment variable
        monkeypatch.setenv("COACH_DB_PATH", str(temp_db_path))

        # Create server without explicit config
        mcp = create_mcp_server()
        assert mcp is not None
        assert mcp.name == "Coach Workout Manager"

    def test_create_server_missing_env_var(self, monkeypatch):
        """Should raise error when COACH_DB_PATH not set."""
        from coach_mcp.server import create_mcp_server

        # Ensure env var is not set
        monkeypatch.delenv("COACH_DB_PATH", raising=False)

        with pytest.raises(ValueError, match="COACH_DB_PATH"):
            create_mcp_server()



@pytest.mark.integration
class TestMCPMain:
    def test_main_module_import(self):
        """Should be able to import the main module."""
        # Just importing should work (doesn't run main)
        from coach_mcp import __main__
        assert hasattr(__main__, 'main')
