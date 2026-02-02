#!/usr/bin/env python3
"""Ingest exercise plans from JSON file into database via MCP tools."""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from coach_mcp.config import MCPConfig
from coach_mcp.server import create_mcp_server


def transform_block_to_exercises(block: dict, block_index: int) -> list:
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
        for i, ex in enumerate(block["exercises"]):
            exercise_id = f"{block_type}_{block_index}_{i+1}"

            # Determine exercise type based on block type and exercise content
            if block_type in ["circuit", "power"]:
                ex_type = "circuit"
            elif block_type == "strength":
                ex_type = "strength"
            elif block_type == "accessory":
                ex_type = "strength"
            else:
                ex_type = "strength"

            # Build exercise entry
            exercise = {
                "id": exercise_id,
                "name": ex.get("name", "Unknown"),
                "type": ex_type,
            }

            # Add sets/reps for strength exercises
            if ex.get("sets"):
                exercise["target_sets"] = ex["sets"] if isinstance(ex["sets"], int) else 3
            if ex.get("reps"):
                exercise["target_reps"] = str(ex["reps"])

            # Build guidance note from various fields
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

        # Determine if it's VO2 max or Zone 2
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


def transform_plan(plan_data: dict) -> dict:
    """Transform block-based plan to flat exercise list format."""
    exercises = []

    for i, block in enumerate(plan_data.get("blocks", [])):
        block_exercises = transform_block_to_exercises(block, i)
        exercises.extend(block_exercises)

    return {
        "day_name": plan_data.get("theme", "Workout"),
        "location": plan_data.get("location", "Home"),
        "phase": plan_data.get("phase", "Foundation"),
        "total_duration_min": plan_data.get("total_duration_min", 60),
        "exercises": exercises
    }


def main():
    # Load the JSON plans
    json_path = Path(__file__).parent.parent / "exercise_plans_json.json"

    if not json_path.exists():
        print(f"Error: {json_path} not found")
        sys.exit(1)

    with open(json_path) as f:
        all_plans = json.load(f)

    print(f"Loaded {len(all_plans)} workout plans from {json_path}")

    # Initialize MCP with database
    db_path = Path(__file__).parent.parent / "coach.db"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        print("Run the server first to initialize the database: python src/server.py")
        sys.exit(1)

    config = MCPConfig(db_path=db_path)
    mcp = create_mcp_server(config)

    # Get the set_workout_plan tool function
    tools = {tool.name: tool for tool in mcp._tool_manager._tools.values()}
    set_plan = tools["set_workout_plan"].fn

    # Ingest each plan
    success_count = 0
    error_count = 0

    for date_str, plan_data in sorted(all_plans.items()):
        try:
            # Transform to MCP format
            transformed = transform_plan(plan_data)

            # Call MCP tool
            result = set_plan(date=date_str, plan=transformed)

            if result.get("success"):
                print(f"  {date_str}: {transformed['day_name']} ({len(transformed['exercises'])} exercises)")
                success_count += 1
            else:
                print(f"  {date_str}: FAILED - {result}")
                error_count += 1

        except Exception as e:
            print(f"  {date_str}: ERROR - {str(e)}")
            error_count += 1

    print(f"\nComplete: {success_count} plans ingested, {error_count} errors")


if __name__ == "__main__":
    main()
