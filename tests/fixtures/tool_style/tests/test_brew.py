from kettle.brew import steep_seconds


def test_spec01_ac1_green_default():
    assert steep_seconds("green") == 120


def test_spec1_ac02_black_default():
    assert steep_seconds("black") == 240
