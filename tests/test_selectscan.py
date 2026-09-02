"""Regression tests for aor_dv10.selectscan - the
purely client-side, AR8200-inspired select-scan feature.
Nothing here touches a real or simulated device directly; run_select_scan()
is tested against a fake tune_fn/sleep_fn so it never needs one.
"""

import pytest

from aor_dv10.selectscan import DEFAULT_MAX_ENTRIES, SelectScanList, run_select_scan


# -- SelectScanList -----------------------------------------------------


def test_add_appends_in_order():
    lst = SelectScanList()
    lst.add(0, 1)
    lst.add(2, 3)
    assert list(lst) == [(0, 1), (2, 3)]
    assert len(lst) == 2


def test_add_deduplicates_silently():
    lst = SelectScanList()
    lst.add(0, 1)
    lst.add(0, 1)  # should not raise, should not duplicate
    assert list(lst) == [(0, 1)]


def test_add_raises_when_full():
    lst = SelectScanList(max_entries=2)
    lst.add(0, 1)
    lst.add(0, 2)
    with pytest.raises(ValueError):
        lst.add(0, 3)


def test_default_max_entries_matches_module_constant():
    lst = SelectScanList()
    assert lst.max_entries == DEFAULT_MAX_ENTRIES


def test_remove_existing_returns_true():
    lst = SelectScanList()
    lst.add(0, 1)
    assert lst.remove(0, 1) is True
    assert list(lst) == []


def test_remove_missing_returns_false():
    lst = SelectScanList()
    assert lst.remove(9, 9) is False


def test_clear_empties_the_list():
    lst = SelectScanList()
    lst.add(0, 1)
    lst.add(0, 2)
    lst.clear()
    assert len(lst) == 0


# -- run_select_scan ------------------------------------------------------


def test_run_select_scan_raises_on_empty_list():
    with pytest.raises(ValueError):
        list(run_select_scan(lambda b, c: None, []))


def test_run_select_scan_tunes_and_yields_every_entry_one_cycle():
    tuned = []
    slept = []
    entries = [(0, 1), (0, 2), (1, 5)]
    results = list(
        run_select_scan(
            lambda b, c: tuned.append((b, c)),
            entries,
            dwell_s=3.0,
            cycles=1,
            sleep_fn=slept.append,
        )
    )
    assert results == entries
    assert tuned == entries
    assert slept == [3.0, 3.0, 3.0]


def test_run_select_scan_respects_cycles():
    tuned = []
    entries = [(0, 1), (0, 2)]
    results = list(
        run_select_scan(
            lambda b, c: tuned.append((b, c)),
            entries,
            cycles=2,
            sleep_fn=lambda s: None,
        )
    )
    assert results == entries + entries
    assert tuned == entries + entries


def test_run_select_scan_should_stop_ends_the_loop_early():
    tuned = []
    entries = [(0, 1), (0, 2), (0, 3)]
    stop_after = 2

    def should_stop():
        return len(tuned) >= stop_after

    results = list(
        run_select_scan(
            lambda b, c: tuned.append((b, c)),
            entries,
            cycles=None,  # would loop forever without should_stop
            sleep_fn=lambda s: None,
            should_stop=should_stop,
        )
    )
    assert results == entries[:stop_after]


def test_run_select_scan_defaults_sleep_fn_to_real_time_sleep(monkeypatch):
    # Doesn't actually sleep for real (dwell_s=0), just confirms the
    # fallback wiring (sleep_fn=None -> time.sleep) doesn't blow up.
    import aor_dv10.selectscan as selectscan_mod

    calls = []
    monkeypatch.setattr(selectscan_mod._time, "sleep", lambda s: calls.append(s))
    list(run_select_scan(lambda b, c: None, [(0, 1)], dwell_s=0.0, cycles=1))
    assert calls == [0.0]
