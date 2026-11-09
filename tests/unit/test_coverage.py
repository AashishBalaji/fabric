import random

from fabric import coverage as cov
from fabric import protocol as proto


def test_directed_bucket_boundaries():
    assert cov.directed_bucket(1) == "directed/n=tiny"
    assert cov.directed_bucket(3) == "directed/n=small"
    assert cov.directed_bucket(8) == "directed/n=medium"
    assert cov.directed_bucket(12) == "directed/n=large"


def test_directed_and_gpio_universe_covers_the_generator_range():
    # Regression: the universe used to only list tiny/small/medium
    # (n<=8) while gen_directed_n/gen_gpio_n draw n in 1..12, so any
    # generated n in 9..12 bucketed to "large" and was silently
    # invisible to closure()/gaps(). Fixed by including "large" in
    # both universes; this test pins that against the real generator
    # range rather than just the bucket edges.
    from fabric import random_gen as rg

    r = random.Random(0)
    for _ in range(500):
        n = rg.gen_directed_n(r)
        assert cov.directed_bucket(n) in cov.DIRECTED_UNIVERSE
        n = rg.gen_gpio_n(r)
        assert cov.gpio_bucket(n) in cov.GPIO_UNIVERSE


def test_coverage_model_persists_across_load_save(tmp_path):
    path = tmp_path / "coverage.json"
    model = cov.CoverageModel.load(path)  # missing file -> empty model
    assert model.closure({"a", "b"}) == 0.0

    model.record("a")
    model.save(path)

    reloaded = cov.CoverageModel.load(path)
    assert reloaded.closure({"a", "b"}) == 0.5

    # A second campaign accumulates on top of the first rather than
    # starting over -- this is the actual point of persistence.
    reloaded.record("b")
    reloaded.save(path)
    final = cov.CoverageModel.load(path)
    assert final.closure({"a", "b"}) == 1.0


def test_coverage_model_closure_starts_at_zero():
    model = cov.CoverageModel()
    assert model.closure({"a", "b"}) == 0.0


def test_coverage_model_records_and_closes():
    model = cov.CoverageModel()
    model.record("a")
    assert model.closure({"a", "b"}) == 0.5
    assert model.gaps({"a", "b"}) == {"b"}


def test_coverage_model_closure_empty_universe_is_complete():
    model = cov.CoverageModel()
    assert model.closure(set()) == 1.0


def test_nested_bucket_no_handler():
    result = proto.parse_nested("N 3 4 3 4")
    assert cov.nested_bucket(result) == "nested/uart_handler_did_not_fire"


def test_nested_bucket_with_nested_ticks():
    result = proto.parse_nested("N 1 3 4 2")
    assert cov.nested_bucket(result) == "nested/ticks_inside=small"


def test_mask_stress_bucket_matches_prediction():
    steps = "ED"
    result = proto.parse_mask_stress("M 0 5 0")  # disabled, correctly not counted
    bucket = cov.mask_stress_bucket(steps, result)
    assert bucket.endswith("/matches_prediction")
    assert "final=disabled" in bucket


def test_mask_stress_bucket_mismatch():
    steps = "ED"
    result = proto.parse_mask_stress("M 1 5 0")  # disabled, but WAS counted -> mismatch
    bucket = cov.mask_stress_bucket(steps, result)
    assert bucket.endswith("/MISMATCH")


def test_full_universe_is_nonempty_and_covers_all_scenarios():
    assert cov.FULL_UNIVERSE
    assert any(b.startswith("directed/") for b in cov.FULL_UNIVERSE)
    assert any(b.startswith("gpio/") for b in cov.FULL_UNIVERSE)
    assert any(b.startswith("nested/") for b in cov.FULL_UNIVERSE)
    assert any(b.startswith("mask_stress/") for b in cov.FULL_UNIVERSE)


def test_mismatches_only_returns_hit_mismatch_buckets():
    model = cov.CoverageModel()
    model.record("mask_stress/len=tiny/final=enabled/MISMATCH")
    model.record("directed/n=tiny")
    assert model.mismatches() == ["mask_stress/len=tiny/final=enabled/MISMATCH"]
