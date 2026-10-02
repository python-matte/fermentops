"""Tests for the Pydantic data models in ``schemas``."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from schemas import (
    Batch,
    BubbleReading,
    ExportOptions,
    GravityReading,
    LogEntry,
    Stage,
)

NOW = datetime(2026, 1, 15, 12, 0)


def batch_kwargs(**overrides):
    fields = dict(
        batch_id="FB-001",
        name="Test",
        volume_l=3.0,
        start_date=NOW,
        expected_duration_days=21,
        original_gravity=1.090,
    )
    fields.update(overrides)
    return fields


class TestBatch:
    def test_defaults(self):
        batch = Batch(**batch_kwargs())
        assert batch.stage is Stage.PRIMARY
        assert batch.product == "Wine"
        assert batch.bubble_log == [] and batch.log == []
        assert batch.latest_bubble_rate is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("batch_id", ""),
            ("name", ""),
            ("volume_l", 0),
            ("volume_l", 10_001),
            ("expected_duration_days", 0),
            ("original_gravity", 0.9),
            ("original_gravity", 1.3),
            ("current_temp_f", 10.0),
            ("current_temp_f", 250.0),
            ("notes", "x" * 2001),
        ],
    )
    def test_rejects_out_of_range_fields(self, field, value):
        with pytest.raises(ValidationError):
            Batch(**batch_kwargs(**{field: value}))

    def test_target_gravity_must_be_below_og(self):
        with pytest.raises(ValidationError, match="below OG"):
            Batch(**batch_kwargs(target_final_gravity=1.090))

    def test_assignment_is_validated(self):
        batch = Batch(**batch_kwargs())
        with pytest.raises(ValidationError):
            batch.current_gravity = 5.0

    def test_latest_bubble_rate_uses_newest_timestamp(self):
        batch = Batch(
            **batch_kwargs(
                bubble_log=[
                    BubbleReading(
                        timestamp=datetime(2026, 1, 15, 10),
                        bubbles_per_minute=40,
                    ),
                    BubbleReading(
                        timestamp=datetime(2026, 1, 14, 10),
                        bubbles_per_minute=5,
                    ),
                ]
            )
        )
        assert batch.latest_bubble_rate == 40

    def test_json_round_trip(self):
        batch = Batch(
            **batch_kwargs(
                log=[LogEntry(timestamp=NOW, message="hello")],
                gravity_log=[GravityReading(timestamp=NOW, sg_measured=1.05)],
            )
        )
        assert Batch.model_validate_json(batch.model_dump_json()) == batch


class TestReadings:
    @pytest.mark.parametrize("rate", [-1, 301])
    def test_bubble_rate_bounds(self, rate):
        with pytest.raises(ValidationError):
            BubbleReading(timestamp=NOW, bubbles_per_minute=rate)

    def test_gravity_reading_defaults_to_calibration_temperature(self):
        reading = GravityReading(timestamp=NOW, sg_measured=1.050)
        assert reading.temp_f == 60.0
        assert reading.sg_corrected is None

    def test_log_message_is_stripped(self):
        assert LogEntry(timestamp=NOW, message="  hi  ").message == "hi"

    @pytest.mark.parametrize("message", ["", "   ", "x" * 501])
    def test_log_message_rejects_blank_and_too_long(self, message):
        with pytest.raises(ValidationError):
            LogEntry(timestamp=NOW, message=message)


class TestExportOptions:
    def test_requires_a_batch(self):
        with pytest.raises(ValidationError):
            ExportOptions(batch_ids=[])

    def test_defaults_include_everything(self):
        options = ExportOptions(batch_ids=["FB-001"])
        assert options.include_alerts
        assert options.include_gravity_log
        assert options.include_activity_log
