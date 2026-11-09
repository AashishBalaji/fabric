from fabric import protocol as proto
from fabric import triage as tri


def test_check_directed_pass():
    assert tri.check_directed(3, proto.DirectedResult(rx_count=3, tick_count=1)) is None


def test_check_directed_undercount():
    f = tri.check_directed(3, proto.DirectedResult(rx_count=1, tick_count=1))
    assert f is not None
    assert f.signature == "directed_undercount"


def test_check_directed_overcount():
    f = tri.check_directed(3, proto.DirectedResult(rx_count=5, tick_count=1))
    assert f.signature == "directed_overcount"


def test_check_gpio_pass():
    assert tri.check_gpio(5, proto.GpioResult(ok=10, fault=0, echoed="ABCDE")) is None


def test_check_gpio_mismatch():
    f = tri.check_gpio(5, proto.GpioResult(ok=5, fault=5, echoed="ABCDE"))
    assert f.signature == "gpio_mismatch"


def test_check_nested_pass():
    r = proto.parse_nested("N 1 3 4 2")
    assert tri.check_nested(r) is None


def test_check_nested_handler_never_fired():
    r = proto.parse_nested("N 3 4 3 4")
    f = tri.check_nested(r)
    assert f.signature == "uart_handler_did_not_fire"


def test_check_nested_priority_not_honored():
    r = proto.parse_nested("N 1 2")  # handler ran, nothing nested inside
    f = tri.check_nested(r)
    assert f.signature == "priority_not_honored"


def test_check_mask_stress_pass():
    r = proto.parse_mask_stress("M 0 5")
    assert tri.check_mask_stress("D", r) is None


def test_check_mask_stress_mismatch():
    r = proto.parse_mask_stress("M 1 5")
    f = tri.check_mask_stress("D", r)
    assert f.signature == "mask_state_mismatch"


def test_triage_engine_clusters_and_ignores_passes():
    engine = tri.TriageEngine()
    engine.record(tri.check_directed(3, proto.DirectedResult(rx_count=1, tick_count=0)))
    engine.record(tri.check_directed(3, proto.DirectedResult(rx_count=3, tick_count=0)))  # pass, ignored
    engine.record(tri.check_directed(2, proto.DirectedResult(rx_count=0, tick_count=0)))
    clusters = engine.clusters()
    assert clusters["directed_undercount"] == 2
    assert len(engine.findings) == 2


def test_every_signature_has_a_catalog_suggestion():
    for signature in tri.CATALOG:
        f = tri.Finding(scenario="x", args={}, signature=signature, detail="", observed=None)
        assert f.suggestion == tri.CATALOG[signature]
