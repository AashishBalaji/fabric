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
