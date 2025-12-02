"""
Admin registrations for core app.

Each model admin lives in its own module to avoid a single gigantic file.
"""

from .medication import MedicationAdmin  # noqa: F401
from .checkup import CheckupLibraryAdmin  # noqa: F401
from .followup import FollowupLibraryAdmin  # noqa: F401
