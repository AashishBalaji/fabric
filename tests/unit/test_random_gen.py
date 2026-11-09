import random

from fabric import random_gen as rg


def test_gen_directed_n_within_bounds():
    r = random.Random(0)
    for _ in range(200):
        n = rg.gen_directed_n(r, lo=1, hi=12)
        assert 1 <= n <= 12


def test_gen_mask_sequence_within_length_bounds_and_alphabet():
    r = random.Random(0)
    for _ in range(200):
        seq = rg.gen_mask_sequence(r, min_len=1, max_len=8)
        assert 1 <= len(seq) <= 8
        assert all(c in rg.MASK_STEPS for c in seq)


def test_gen_directed_n_is_biased_toward_boundaries_not_uniform():
    # A plain uniform sampler over 1..12 would pass every test above --
    # these only check range/alphabet, which say nothing about shape.
    # This pins the actual point of "constrained-random": boundary
    # values should show up far more than a 1/12 uniform share would
    # predict. A regression back to plain randint(lo, hi) should fail
    # this test even though it would still pass the ones above.
    r = random.Random(0)
    draws = [rg.gen_directed_n(r) for _ in range(2000)]
    boundary_share = sum(1 for n in draws if n in (1, 12)) / len(draws)
    assert boundary_share > 0.25  # uniform over 1..12 would give ~1/6 = 0.167


def test_gen_mask_sequence_forces_known_bug_triggering_adjacency():
    # An earlier version of this test checked "ED"/"DE" adjacency
    # against a threshold of 0.2 -- but with only 3 symbols (E/D/T) and
    # lengths 2-8, a PLAIN UNIFORM sampler produces that adjacency
    # incidentally about 56% of the time on its own (measured), so that
    # threshold passed for both the real generator and a reverted,
    # uniform one -- it had no teeth. A repeated-step run ("EEEE",
    # "DDDD", ...) is a much cleaner signal: the real generator forces
    # it deliberately (~20%, measured), while a uniform sampler over
    # length>=2 produces it only by chance (~7%, measured) -- an
    # 8-point-plus gap wide enough for a real regression back to
    # uniform sampling to actually fail this.
    r = random.Random(0)
    seqs = [rg.gen_mask_sequence(r, min_len=2, max_len=8) for _ in range(5000)]
    all_same_step = sum(1 for s in seqs if len(set(s)) == 1)
    assert all_same_step / len(seqs) > 0.15

    # Also keep an adjacency check, just with a threshold that reflects
    # the real combined rate (forced + incidental, ~63% measured) rather
    # than one indistinguishable from the ~56% uniform baseline.
    has_adjacency = sum(1 for s in seqs if "ED" in s or "DE" in s)
    assert has_adjacency / len(seqs) > 0.6


def test_gen_plans_is_reproducible_for_same_seed():
    a = rg.gen_plans(seed=42, count=25)
    b = rg.gen_plans(seed=42, count=25)
    assert a == b


def test_gen_plans_differs_for_different_seeds_most_of_the_time():
    a = rg.gen_plans(seed=1, count=25)
    b = rg.gen_plans(seed=2, count=25)
    assert a != b


def test_gen_plans_only_produces_known_scenarios():
    plans = rg.gen_plans(seed=7, count=100)
    known = {"directed", "gpio", "nested", "mask_stress"}
    assert all(scenario in known for scenario, _ in plans)
