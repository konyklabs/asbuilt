from farebox.pricing import FREE_MINUTES, free_minutes

EXPECTED_FREE_MINUTES = 15


def test_free_minutes_matches_constant():
    assert free_minutes() == FREE_MINUTES


def test_free_minutes_matches_expected():
    assert FREE_MINUTES == EXPECTED_FREE_MINUTES
