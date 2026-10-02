"""Pydantic data models for FermentOps.

All physical quantities are stored in canonical units (litres, degrees
Fahrenheit, specific gravity as a dimensionless ratio). Unit conversion for
display is the responsibility of the UI layer via ``core_logic``.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --- Shared validation bounds ------------------------------------------------
SG_MIN: float = 0.980
SG_MAX: float = 1.200
TEMP_MIN_F: float = 32.0
TEMP_MAX_F: float = 212.0


class Stage(str, Enum):
    """Lifecycle stage of a ferment."""

    PRIMARY = "Primary"
    SECONDARY = "Secondary"
    COLD_CRASH = "Cold Crash"
    AGING = "Aging"


class UnitSystem(str, Enum):
    """Display unit system selectable in the UI."""

    METRIC = "Metric"
    IMPERIAL = "Imperial"


class LogKind(str, Enum):
    """Category of a production-log entry."""

    NOTE = "Note"
    ADDITION = "Addition"
    TRANSFER = "Transfer"
    TASTING = "Tasting"


class BubbleReading(BaseModel):
    """A single airlock bubble-rate observation."""

    timestamp: datetime
    bubbles_per_minute: float = Field(ge=0, le=300)


class GravityReading(BaseModel):
    """A hydrometer reading, stored raw with its measurement temperature."""

    timestamp: datetime
    sg_measured: float = Field(ge=SG_MIN, le=SG_MAX)
    temp_f: float = Field(default=60.0, ge=TEMP_MIN_F, le=TEMP_MAX_F)
    sg_corrected: Optional[float] = Field(default=None, ge=SG_MIN, le=SG_MAX)


class LogEntry(BaseModel):
    """A free-form production-log entry."""

    timestamp: datetime
    kind: LogKind = LogKind.NOTE
    message: str = Field(min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class Batch(BaseModel):
    """A single active micro-batch ferment."""

    model_config = ConfigDict(validate_assignment=True)

    batch_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    product: str = Field(default="Wine", max_length=60)
    volume_l: float = Field(gt=0, le=10_000)
    start_date: datetime
    stage: Stage = Stage.PRIMARY
    expected_duration_days: int = Field(gt=0, le=3650)
    original_gravity: float = Field(ge=SG_MIN, le=SG_MAX)
    target_final_gravity: Optional[float] = Field(
        default=None, ge=SG_MIN, le=SG_MAX
    )
    current_gravity: Optional[float] = Field(
        default=None, ge=SG_MIN, le=SG_MAX
    )
    current_temp_f: Optional[float] = Field(
        default=None, ge=TEMP_MIN_F, le=TEMP_MAX_F
    )
    bubble_log: List[BubbleReading] = Field(default_factory=list)
    gravity_log: List[GravityReading] = Field(default_factory=list)
    log: List[LogEntry] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _check_gravities(self) -> "Batch":
        """Target final gravity must sit below original gravity."""
        if (
            self.target_final_gravity is not None
            and self.target_final_gravity >= self.original_gravity
        ):
            raise ValueError("target_final_gravity must be below OG")
        return self

    @property
    def latest_bubble_rate(self) -> Optional[float]:
        """Most recent airlock bubble rate, or ``None`` if never logged."""
        if not self.bubble_log:
            return None
        latest = max(self.bubble_log, key=lambda r: r.timestamp)
        return latest.bubbles_per_minute


class ExportOptions(BaseModel):
    """User-selected options for the Markdown production sheet."""

    batch_ids: List[str] = Field(min_length=1)
    include_gravity_log: bool = True
    include_activity_log: bool = True
    include_alerts: bool = True
