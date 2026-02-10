"""Tests for _transform_block_to_exercises, _transform_block_plan, and _is_bodyweight_or_band."""

import pytest

from coach_mcp.server import (
    _is_bodyweight_or_band,
    _transform_block_to_exercises,
    _transform_block_plan,
    _get_coach_plan_guide,
)


# --- rounds parsing ---

def _make_circuit_block(exercises, rest_guidance="", block_type="circuit", rounds=None):
    block = {
        "block_type": block_type,
        "title": "Test Block",
        "rest_guidance": rest_guidance,
        "exercises": exercises,
    }
    if rounds is not None:
        block["rounds"] = rounds
    return block


class TestRoundsParsing:
    def test_circuit_4_rounds(self):
        block = _make_circuit_block(
            [{"name": "KB Swings", "reps": 10}],
            rounds=4,
        )
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["target_sets"] == 4

    def test_power_block_rounds(self):
        block = _make_circuit_block(
            [{"name": "Box Jump", "reps": 5}],
            rounds=5,
            block_type="power",
        )
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["target_sets"] == 5

    def test_no_rounds_no_target_sets(self):
        block = _make_circuit_block(
            [{"name": "KB Swings", "reps": 10}],
        )
        results = _transform_block_to_exercises(block, 0)
        assert "target_sets" not in results[0]

    def test_explicit_sets_override_rounds(self):
        block = _make_circuit_block(
            [{"name": "KB Swings", "reps": 10, "sets": 2}],
            rounds=4,
        )
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["target_sets"] == 2


# --- hide_weight ---

class TestHideWeight:
    @pytest.mark.parametrize("name", [
        "Push-ups",
        "Band Pull-Aparts",
        "Bodyweight Squat Hold",
        "Banded Face Pulls",
        "Jump Squat",
        "Plank Hold",
        "Dead Hang",
        "Wall Sit",
        "Glute Bridge",
    ])
    def test_bodyweight_or_band_exercises_hidden(self, name):
        block = _make_circuit_block([{"name": name, "reps": 10}])
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("hide_weight") is True

    @pytest.mark.parametrize("name", [
        "KB Swings",
        "Farmer's Carry",
        "Dumbbell Row",
        "Barbell Squat",
    ])
    def test_weighted_exercises_not_hidden(self, name):
        block = _make_circuit_block([{"name": name, "reps": 10}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_hide_weight_applies_to_strength_block(self):
        block = {
            "block_type": "strength",
            "title": "Strength",
            "rest_guidance": "",
            "exercises": [{"name": "Push-ups", "reps": 10}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("hide_weight") is True


# --- guidance_note includes rest_guidance ---

class TestGuidanceNote:
    def test_circuit_excludes_rest_guidance(self):
        block = _make_circuit_block(
            [{"name": "KB Swings", "reps": 10}],
            rest_guidance="90 sec rest after each round",
            rounds=4,
        )
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("guidance_note") is None

    def test_power_excludes_rest_guidance(self):
        block = _make_circuit_block(
            [{"name": "Box Jump", "reps": 5, "notes": "Explosive"}],
            rest_guidance="60 sec rest after each round",
            rounds=5,
            block_type="power",
        )
        results = _transform_block_to_exercises(block, 0)
        assert "60 sec rest" not in results[0]["guidance_note"]
        assert "Explosive" in results[0]["guidance_note"]

    def test_circuit_exercise_notes_still_shown(self):
        block = _make_circuit_block(
            [{"name": "KB Swings", "reps": 10, "load_guide": "Heavy"}],
            rounds=4,
        )
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["guidance_note"] == "Heavy"

    def test_strength_includes_rest_guidance(self):
        block = {
            "block_type": "strength",
            "title": "Strength",
            "rest_guidance": "Rest 2-3 min",
            "exercises": [{"name": "Squat", "reps": 5}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert "Rest 2-3 min" in results[0]["guidance_note"]


# --- show_time for duration-based reps ---

class TestShowTime:
    @pytest.mark.parametrize("reps", [
        "30 sec",
        "30 sec/side",
        "45 seconds",
        "20 SEC",
    ])
    def test_duration_reps_set_show_time(self, reps):
        block = _make_circuit_block([{"name": "Wall Sit", "reps": reps}])
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("show_time") is True
        assert results[0]["target_reps"] == reps

    @pytest.mark.parametrize("reps", [
        10,
        "10",
        "8/leg",
        "10/side",
    ])
    def test_non_duration_reps_no_show_time(self, reps):
        block = _make_circuit_block([{"name": "KB Swings", "reps": reps}])
        results = _transform_block_to_exercises(block, 0)
        assert "show_time" not in results[0]

    def test_no_reps_no_show_time(self):
        block = _make_circuit_block([{"name": "KB Swings"}])
        results = _transform_block_to_exercises(block, 0)
        assert "show_time" not in results[0]


# --- _is_bodyweight_or_band ---

class TestIsBodyweightOrBand:
    def test_pushup_variants(self):
        assert _is_bodyweight_or_band("Push-ups") is True
        assert _is_bodyweight_or_band("Pushup") is True
        assert _is_bodyweight_or_band("Wide Push Up") is True

    def test_band_exercises(self):
        assert _is_bodyweight_or_band("Band Pull-Aparts") is True
        assert _is_bodyweight_or_band("Banded Face Pulls") is True

    def test_weighted_exercises(self):
        assert _is_bodyweight_or_band("KB Swings") is False
        assert _is_bodyweight_or_band("Barbell Squat") is False


# --- equipment field ---

class TestEquipmentField:
    def test_bodyweight_equipment_hides_weight(self):
        block = _make_circuit_block([{"name": "Mountain Climbers", "reps": 20, "equipment": "bodyweight"}])
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("hide_weight") is True

    def test_band_equipment_hides_weight(self):
        block = _make_circuit_block([{"name": "Face Pulls", "reps": 15, "equipment": "band"}])
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("hide_weight") is True

    def test_kettlebell_equipment_shows_weight(self):
        block = _make_circuit_block([{"name": "KB Swings", "reps": 15, "equipment": "kettlebell"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_dumbbell_equipment_shows_weight(self):
        block = _make_circuit_block([{"name": "DB Row", "reps": 10, "equipment": "dumbbell"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_barbell_equipment_shows_weight(self):
        block = _make_circuit_block([{"name": "Barbell Squat", "reps": 5, "equipment": "barbell"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_machine_equipment_shows_weight(self):
        block = _make_circuit_block([{"name": "Leg Press", "reps": 12, "equipment": "machine"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_equipment_overrides_name_heuristic(self):
        """An exercise with 'push-up' in name but dumbbell equipment should show weight."""
        block = _make_circuit_block([{"name": "DB Push-up Press", "reps": 10, "equipment": "dumbbell"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]

    def test_missing_equipment_falls_back_to_heuristic(self):
        """Without equipment field, name-based heuristic still works."""
        block = _make_circuit_block([{"name": "Push-ups", "reps": 10}])
        results = _transform_block_to_exercises(block, 0)
        assert results[0].get("hide_weight") is True

    def test_unknown_equipment_shows_weight(self):
        """Unknown equipment values should not hide weight."""
        block = _make_circuit_block([{"name": "Suspension Row", "reps": 10, "equipment": "trx"}])
        results = _transform_block_to_exercises(block, 0)
        assert "hide_weight" not in results[0]


# --- warmup block transform ---

class TestWarmupBlock:
    def test_warmup_with_int_reps(self):
        """Warmup exercises with integer reps use 'xN' format."""
        block = {
            "block_type": "warmup",
            "title": "Warmup",
            "exercises": [{"name": "Cat-Cow", "reps": 10}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert len(results) == 1
        assert results[0]["type"] == "checklist"
        assert "Cat-Cow x10" in results[0]["items"]

    def test_warmup_with_string_reps(self):
        """Warmup exercises with string reps append directly."""
        block = {
            "block_type": "warmup",
            "title": "Warmup",
            "exercises": [{"name": "Bird-Dog", "reps": "5/side"}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert "Bird-Dog 5/side" in results[0]["items"]

    def test_warmup_with_no_reps(self):
        """Warmup exercises without reps just use name."""
        block = {
            "block_type": "warmup",
            "title": "Warmup",
            "exercises": [{"name": "Standard Warmup Routine"}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert "Standard Warmup Routine" in results[0]["items"]

    def test_warmup_uses_title(self):
        """Warmup block uses its title as the exercise name."""
        block = {
            "block_type": "warmup",
            "title": "The Stability Start",
            "exercises": [{"name": "Cat-Cow", "reps": 10}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["name"] == "The Stability Start"

    def test_warmup_fallback_name(self):
        """Warmup block without title defaults to 'Warmup'."""
        block = {
            "block_type": "warmup",
            "exercises": [{"name": "Cat-Cow", "reps": 10}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["name"] == "Warmup"


# --- cardio/instruction blocks ---

class TestCardioInstructionBlock:
    def test_zone2_cardio_block(self):
        """Cardio block with instructions becomes a duration exercise."""
        block = {
            "block_type": "cardio",
            "title": "Zone 2 Flush",
            "duration_min": 15,
            "instructions": ["Equipment: Exercise Bike", "Strict 135-145 bpm"],
        }
        results = _transform_block_to_exercises(block, 0)
        assert len(results) == 1
        assert results[0]["type"] == "duration"
        assert results[0]["name"] == "Zone 2 Flush"
        assert results[0]["target_duration_min"] == 15
        assert "Exercise Bike" in results[0]["guidance_note"]

    def test_vo2_interval_block(self):
        """Cardio block with VO2 keyword becomes an interval exercise."""
        block = {
            "block_type": "cardio",
            "title": "VO2 Max Session",
            "duration_min": 20,
            "instructions": ["3 min warmup", "4x4 min VO2 intervals", "3 min cooldown"],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["type"] == "interval"
        assert results[0]["name"] == "VO2 Max Intervals"

    def test_hard_interval_block(self):
        """Cardio block with HARD keyword becomes an interval exercise."""
        block = {
            "block_type": "cardio",
            "title": "HIIT",
            "duration_min": 10,
            "instructions": ["30 sec HARD sprint", "90 sec recovery", "Repeat 6x"],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["type"] == "interval"

    def test_cardio_fallback_name(self):
        """Cardio block without title defaults to 'Zone 2 Cardio'."""
        block = {
            "block_type": "cardio",
            "duration_min": 20,
            "instructions": ["Maintain HR 135-148 bpm"],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["name"] == "Zone 2 Cardio"

    def test_cardio_exercise_id(self):
        """Cardio instruction block gets correct exercise ID."""
        block = {
            "block_type": "cardio",
            "title": "Cardio",
            "duration_min": 15,
            "instructions": ["Easy pace"],
        }
        results = _transform_block_to_exercises(block, 2)
        assert results[0]["id"] == "cardio_2_1"


# --- unknown block type fallback ---

class TestUnknownBlockType:
    def test_unknown_block_type_defaults_to_strength(self):
        """Exercises in an unrecognized block type default to strength."""
        block = {
            "block_type": "mobility",
            "title": "Mobility",
            "exercises": [{"name": "Hip Circles", "reps": 10}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert results[0]["type"] == "strength"


# --- tempo in guidance ---

class TestTempoGuidance:
    def test_tempo_included_in_guidance(self):
        """Tempo field appears in guidance note."""
        block = {
            "block_type": "strength",
            "title": "Strength",
            "rest_guidance": "",
            "exercises": [{"name": "Squat", "reps": 5, "tempo": "3-1-1"}],
        }
        results = _transform_block_to_exercises(block, 0)
        assert "Tempo 3-1-1" in results[0]["guidance_note"]


# --- _transform_block_plan ---

class TestTransformBlockPlan:
    def test_basic_transform(self):
        """Transform a plan with one strength block."""
        plan_data = {
            "theme": "Lower Body",
            "location": "Gym",
            "phase": "Building",
            "total_duration_min": 45,
            "blocks": [
                {
                    "block_type": "strength",
                    "title": "Strength Block",
                    "duration_min": 30,
                    "exercises": [{"name": "Squat", "sets": 3, "reps": 5}],
                }
            ],
        }
        result = _transform_block_plan(plan_data)
        assert result["day_name"] == "Lower Body"
        assert result["location"] == "Gym"
        assert result["phase"] == "Building"
        assert result["total_duration_min"] == 45
        assert len(result["blocks"]) == 1
        assert len(result["blocks"][0]["exercises"]) == 1

    def test_defaults_when_fields_missing(self):
        """Missing fields get sensible defaults."""
        plan_data = {"blocks": []}
        result = _transform_block_plan(plan_data)
        assert result["day_name"] == "Workout"
        assert result["location"] == "Home"
        assert result["phase"] == "Foundation"
        assert result["total_duration_min"] == 60

    def test_multiple_blocks_have_exercises(self):
        """Exercises from multiple blocks are in their respective blocks."""
        plan_data = {
            "theme": "Full Body",
            "blocks": [
                {
                    "block_type": "warmup",
                    "title": "Warmup",
                    "exercises": [{"name": "Cat-Cow", "reps": 10}],
                },
                {
                    "block_type": "strength",
                    "title": "Strength",
                    "exercises": [{"name": "Squat", "sets": 3, "reps": 5}],
                },
                {
                    "block_type": "cardio",
                    "title": "Cardio",
                    "duration_min": 15,
                    "instructions": ["Zone 2 at 140 bpm"],
                },
            ],
        }
        result = _transform_block_plan(plan_data)
        assert len(result["blocks"]) == 3
        total_exercises = sum(len(b["exercises"]) for b in result["blocks"])
        assert total_exercises == 3


# --- coach plan guide ---

class TestCoachPlanGuide:
    def test_guide_returns_nonempty_string(self):
        """The coach plan guide should return a non-empty string."""
        guide = _get_coach_plan_guide()
        assert isinstance(guide, str)
        assert len(guide) > 100

    def test_guide_contains_key_sections(self):
        """The guide should reference key tools and structure."""
        guide = _get_coach_plan_guide()
        assert "set_workout_plan" in guide
        assert "exercises" in guide
