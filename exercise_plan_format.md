# LLM Exercise Plan Generation Format

This document defines the structured JSON format that LLMs must use when creating or revising exercise plans for the Exercise Tracker. This structure is designed to be ingested via the `set_workout_plan` or `ingest_training_program` MCP tools, which store plans in normalized relational tables (`workout_sessions`, `session_blocks`, `planned_exercises`).

## 1. Output Requirement

When asked to generate a plan for a specific date or range of dates, produce a **JSON object** for each day.
*   **Do not** include nutrition, sleep, or supplement notes.
*   **Do not** include general Markdown tables unless specifically asked for a visual summary.
*   **Do** strictly adhere to the schema below.

## 2. JSON Schema Definition

The root object represents a single day's workout.

```json
{
  "phase": "string (e.g., 'Foundation', 'Building', 'Intensity')",
  "theme": "string (e.g., 'Lower Body Emphasis + Conditioning')",
  "total_duration_min": "integer (estimated total session time)",
  "blocks": [
    {
      "block_type": "string (enum: 'warmup', 'strength', 'cardio', 'circuit', 'accessory', 'power')",
      "title": "string (e.g., 'Strength Block', 'Zone 2 Flush')",
      "duration_min": "integer (estimated block time)",
      "rest_guidance": "string (optional, e.g., 'Rest until HR <= 130')",
      "rounds": "integer (optional, for circuit/power blocks - number of rounds)",
      "exercises": [
        {
          "name": "string (Exercise Name)",
          "sets": "string | integer (optional)",
          "reps": "string | integer (optional)",
          "tempo": "string (optional, e.g., '3-1-1')",
          "rest": "string (optional specific rest per exercise)",
          "load_guide": "string (optional, e.g., 'RPE 7-8', 'Heaviest KB')",
          "notes": "string (optional technique cues)",
          "equipment": "string (optional, enum: 'bodyweight', 'band', 'kettlebell', 'dumbbell', 'barbell', 'machine', 'cable')"
        }
      ],
      "instructions": [
        "string (Use this array for Cardio/Interval steps where 'exercises' structure doesn't fit)"
      ]
    }
  ]
}
```

## 3. Reference Examples

### Example 1: Strength + Cardio (Based on Week 1 Monday)

```json
{
  "phase": "Foundation",
  "theme": "Lower Body Emphasis + Conditioning",
  "total_duration_min": 60,
  "blocks": [
    {
      "block_type": "warmup",
      "title": "The Stability Start",
      "duration_min": 10,
      "exercises": [
        { "name": "Cat-Cow", "reps": 10, "notes": "slow, segmental spine movement" },
        { "name": "Bird-Dog", "reps": "5/side", "notes": "5-second hold, squeeze glute hard" },
        { "name": "Dead Bug", "reps": 10, "notes": "press low back into floor" },
        { "name": "Single-Leg Balance", "reps": "30 sec/side", "notes": "barefoot, eyes open then closed" },
        { "name": "Thoracic Rotations", "reps": "5/side", "notes": "open chest toward ceiling" },
        { "name": "Leg Swings", "reps": "10/direction", "notes": "front-to-back and side-to-side" }
      ]
    },
    {
      "block_type": "strength",
      "title": "Strength Block",
      "duration_min": 35,
      "rest_guidance": "Rest until HR ≤ 130 (typically 90-120 sec)",
      "exercises": [
        { "name": "KB Goblet Squat", "sets": 3, "reps": 10, "tempo": "3-1-1", "notes": "Parallel depth, heels down" },
        { "name": "DB Romanian Deadlift", "sets": 3, "reps": 10, "tempo": "3-1-1", "notes": "Feel hamstring stretch" },
        { "name": "DB Reverse Lunge", "sets": 3, "reps": "8/leg", "tempo": "2-1-1", "notes": "Step back, knee hovers" },
        { "name": "Single-Leg Glute Bridge", "sets": 3, "reps": "10/leg", "tempo": "2-2-1", "notes": "Squeeze at top 2 sec" },
        { "name": "DB Single-Arm Row", "sets": 3, "reps": "10/side", "tempo": "2-1-1", "notes": "Pull to hip, squeeze" }
      ]
    },
    {
      "block_type": "cardio",
      "title": "Conditioning Block",
      "duration_min": 15,
      "instructions": [
        "Equipment: Exercise Bike",
        "5 min easy warm-up (HR <130)",
        "10 min STRICT Zone 2 (HR 135-148)",
        "Log average HR. Target: 140-145 bpm"
      ]
    }
  ]
}
```

### Example 2: Heavy Compound + Zone 2 (Based on Week 1 Wednesday)

```json
{
  "phase": "Foundation",
  "theme": "Heavy Compound + Zone 2 Base",
  "total_duration_min": 70,
  "blocks": [
    {
      "block_type": "warmup",
      "title": "The Stability Start",
      "duration_min": 10,
      "exercises": [
        { "name": "Cat-Cow", "reps": 10 },
        { "name": "Bird-Dog", "reps": "5/side" },
        { "name": "Dead Bug", "reps": 10 },
        { "name": "Single-Leg Balance", "reps": "30 sec/side" },
        { "name": "Thoracic Rotations", "reps": "5/side" },
        { "name": "Leg Swings", "reps": "20/leg" }
      ]
    },
    {
      "block_type": "strength",
      "title": "Heavy Strength Block",
      "duration_min": 35,
      "rest_guidance": "Rest until HR ≤ 120-130 (typically 2-3 min)",
      "notes": "Not a circuit. Full recovery between sets.",
      "exercises": [
        { "name": "Trap Bar Deadlift", "sets": 4, "reps": 5, "load_guide": "RPE 7-8", "notes": "Warm up: Bar only, 50%, 70%" },
        { "name": "Assisted Dips", "sets": 3, "reps": "6-8", "load_guide": "RPE 7-8", "notes": "Control descent 2 sec" },
        { "name": "Barbell Row", "sets": 3, "reps": 8, "load_guide": "RPE 7", "notes": "Strict form, no kipping" }
      ]
    },
    {
      "block_type": "cardio",
      "title": "Zone 2 Block",
      "duration_min": 25,
      "instructions": [
        "Equipment: Elliptical",
        "Ideal: 40 min Zone 2 (if time permits)",
        "Minimum: 15-20 min Zone 2 (if limited to 60 min)",
        "Maintain HR 135-148 bpm",
        "Prioritize strength rest periods over Zone 2 duration"
      ]
    }
  ]
}
```

### Example 3: Circuit (Based on Week 1 Friday)

```json
{
  "phase": "Foundation",
  "theme": "Full Body Circuit + Zone 2 Flush",
  "total_duration_min": 60,
  "blocks": [
    {
      "block_type": "warmup",
      "title": "The Stability Start",
      "duration_min": 10,
      "exercises": [
         { "name": "Standard Warmup Routine" }
      ]
    },
    {
      "block_type": "circuit",
      "title": "Circuit Block",
      "duration_min": 35,
      "rest_guidance": "90 sec rest after each round",
      "rounds": 4,
      "exercises": [
        { "name": "KB Swings", "reps": 15, "notes": "Powerful hip snap", "equipment": "kettlebell" },
        { "name": "Push-ups", "reps": "Max", "notes": "Stop 2 shy of failure, perfect form", "equipment": "bodyweight" },
        { "name": "Band Pull-Aparts", "reps": 20, "notes": "Squeeze shoulder blades", "equipment": "band" },
        { "name": "Bodyweight Squat Hold", "reps": "30 sec", "notes": "Parallel depth, static hold", "equipment": "bodyweight" },
        { "name": "Single-Arm Overhead Carry", "reps": "30 sec/side", "notes": "Heavy KB, tight core", "equipment": "kettlebell" }
      ]
    },
    {
      "block_type": "accessory",
      "title": "Leg Accessory Block",
      "duration_min": 10,
      "exercises": [
        { "name": "Single-Leg Calf Raises", "sets": 2, "reps": "15/leg", "notes": "slow eccentric", "equipment": "dumbbell" },
        { "name": "Banded Lateral Walks", "sets": 2, "reps": "15/direction", "equipment": "band" }
      ]
    },
    {
      "block_type": "cardio",
      "title": "Zone 2 Flush",
      "duration_min": 15,
      "instructions": [
        "Equipment: Exercise Bike",
        "Strict 135-145 bpm",
        "Active recovery, not a push"
      ]
    }
  ]
}
```
