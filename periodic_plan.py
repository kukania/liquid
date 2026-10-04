"""Data model for a plan that applies over a range of months."""

from dataclasses import dataclass, field
from uuid import uuid4

from box import TimelineBox
from projection import cents


@dataclass
class PeriodicPlanEdge:
    """Editable directed transfer between two money objects."""

    source_id: str
    destination_id: str
    start_month: int = 0
    end_month: int = 11
    amount: float = 0.0
    use_rest: bool = False
    priority: int = 1
    edge_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        if not 0 <= self.start_month <= self.end_month <= 11:
            raise ValueError("Edge period must be a valid inclusive month range.")
        self.amount = float(self.amount)
        cents(self.amount)
        if self.amount < 0:
            raise ValueError("Edge amount must be zero or greater.")
        if self.priority < 1:
            raise ValueError("Edge priority must be one or greater.")

    @property
    def amount_label(self):
        return "Rest" if self.use_rest else f"${self.amount:,.2f}"


@dataclass
class PeriodicPlan:
    """A collection of timeline boxes repeated across a range of months.

    Month values use the same zero-based indexes as ``MonthlyTimeline``:
    January is ``0`` and December is ``11``.
    """

    start_month: int
    end_month: int
    contents: list[TimelineBox] = field(default_factory=list)
    title: str = "Periodic plan"
    source: str = ""
    destination: str = ""
    amount: float = 0.0
    use_rest: bool = False
    priority: int = 1
    edge_id: str = ""
    source_object_id: str = ""
    destination_object_id: str = ""

    def __post_init__(self):
        """Validate the inclusive month range."""
        cents(self.amount)
        if not 0 <= self.start_month <= 11:
            raise ValueError("start_month must be between 0 and 11.")
        if not 0 <= self.end_month <= 11:
            raise ValueError("end_month must be between 0 and 11.")
        if self.start_month > self.end_month:
            raise ValueError("start_month must be before or equal to end_month.")
        if self.amount < 0:
            raise ValueError("amount must be zero or greater.")
        if self.priority < 1:
            raise ValueError("priority must be one or greater.")

    @property
    def amount_label(self):
        """Return the fixed amount or the remainder-allocation label."""
        return "Rest of money" if self.use_rest else f"${self.amount:,.2f}"

    @property
    def active_months(self) -> tuple[int, ...]:
        """Return every month in which this plan should be shown."""
        return tuple(range(self.start_month, self.end_month + 1))

    def is_active_in(self, month_index: int) -> bool:
        """Return whether the plan should be shown in a month."""
        return month_index in self.active_months
