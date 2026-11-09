import pytest

from fabric import protocol as proto


def test_encode_directed():
    assert proto.encode_directed(3) == b"D\x03"


def test_encode_directed_rejects_out_of_range():
    with pytest.raises(ValueError):
        proto.encode_directed(256)


def test_directed_stimulus_default_pattern_has_right_length():
    assert len(proto.directed_stimulus(5)) == 5


def test_directed_stimulus_explicit_pattern_must_match_length():
    with pytest.raises(ValueError):
        proto.directed_stimulus(3, b"ab")


def test_parse_directed_happy_path():
    r = proto.parse_directed("D 3 17")
    assert r.rx_count == 3
    assert r.tick_count == 17


def test_parse_directed_rejects_garbage():
    with pytest.raises(proto.ProtocolError):
        proto.parse_directed("garbage")


def test_parse_gpio_splits_echo_from_counts():
    r = proto.parse_gpio("ABCDEG 10 0")
    assert r.echoed == "ABCDE"
    assert r.ok == 10
    assert r.fault == 0


def test_parse_nested_log_tuple():
    r = proto.parse_nested("N 1 3 4 2")
    assert r.log == (1, 3, 4, 2)
    assert r.uart_handler_ran is True
    assert r.ticks_nested_inside_uart_handler == 1


def test_nested_ticks_inside_counts_only_between_enter_and_exit():
    # a tick that landed before UART even started shouldn't count
    r = proto.parse_nested("N 3 4 1 2")
    assert r.ticks_nested_inside_uart_handler == 0


def test_nested_no_uart_entry_means_zero_nested_ticks():
    r = proto.parse_nested("N 3 4 3 4")
    assert r.uart_handler_ran is False
    assert r.ticks_nested_inside_uart_handler == 0


@pytest.mark.parametrize(
    "steps,expected_enabled",
    [
        ("D", False),
        ("E", True),
        ("ED", False),
        ("DE", True),
        ("EDT", False),
        ("T", False),  # starts disabled, T doesn't change it
        ("ET", True),
    ],
)
def test_final_mask_state(steps, expected_enabled):
    assert proto.final_mask_state(steps) == expected_enabled


def test_parse_mask_stress_probe_counted():
    r = proto.parse_mask_stress("M 1 9")
    assert r.probe_was_counted is True


def test_parse_mask_stress_probe_not_counted():
    r = proto.parse_mask_stress("M 0 9")
    assert r.probe_was_counted is False


def test_encode_mask_stress_rejects_invalid_step():
    with pytest.raises(ValueError):
        proto.encode_mask_stress("EDX")


def test_encode_mask_stress_rejects_empty():
    with pytest.raises(ValueError):
        proto.encode_mask_stress("")


def test_encode_mask_stress_wire_format():
    assert proto.encode_mask_stress("EDT") == b"M\x03EDT"
