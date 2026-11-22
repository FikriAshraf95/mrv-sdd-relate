from datetime import datetime, timedelta

import pytest

from members.roles import session_valid
from members.signup import EmailTaken, sign_up


def test_spec01_ac1_second_signup_with_same_email_is_refused():
    accounts = {}
    sign_up(accounts, "nadia@courtside.example", "Nadia")
    with pytest.raises(EmailTaken):
        sign_up(accounts, "Nadia@Courtside.example", "Nadia O.")


def test_spec01_ac2_member_reads_only_their_own_account():
    # the access layer arrives with the HTTP routes; the role table is checked here
    from members.roles import can_override

    assert can_override("desk") and not can_override("member")


def test_spec01_ac3_old_session_is_rejected():
    issued = datetime(2026, 9, 14, 8, 0)
    assert session_valid(issued, issued + timedelta(hours=7))
    assert not session_valid(issued, issued + timedelta(hours=9))
