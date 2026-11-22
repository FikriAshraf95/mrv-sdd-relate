from datetime import datetime

import pytest

from waitlist.join import join


def test_spec05_ac1_free_slot_cannot_be_waitlisted():
    with pytest.raises(ValueError):
        join([], "c1", "m1", datetime(2026, 11, 20, 18), slot_taken=False)
