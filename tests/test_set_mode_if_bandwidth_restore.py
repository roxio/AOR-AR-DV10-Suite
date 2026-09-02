"""Regression tests for set_mode() restoring the
shared IF-bandwidth register when switching digital mode off.

Bug report: widen FM to IF1 (100 kHz), switch digital mode on and back
off, and the analog side comes back reading the digital reception's
narrow IF3 (15 kHz) instead of the IF1 that was set before switching. See
DV10Device.set_mode()'s docstring for the full writeup: the AR-DV10's IF
selector is one raw register shared by every demodulation type, and this
project can't stop the firmware from doing that, so set_mode() snapshots
the pre-digital IF value and restores it on the way back to digital off.
"""

from aor_dv10.device import DV10Device


def test_set_mode_restores_if_bandwidth_after_digital_round_trip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")  # digital off, analog FM
        dev.set_if_bandwidth(1)  # FM/IF1 = 100 kHz, per IF_BANDWIDTH_HZ["FM"]
        assert dev.get_if_bandwidth() == "1"

        dev.set_mode("00")  # digital on (Auto)
        # Simulate the real firmware narrowing the shared IF register
        # during digital reception - nothing in this project's own code
        # does this; it's the hardware behavior being worked around.
        dev._chan.write("IF", "3")
        assert dev.get_if_bandwidth() == "3"

        dev.set_mode("F0")  # back to digital off
        assert dev.get_if_bandwidth() == "1", (
            "set_mode() should have restored the pre-digital IF bandwidth"
        )


def test_set_mode_does_not_resnapshot_across_digital_to_digital_hops():
    """Cycling through several digital submodes before returning to off
    must snapshot ONCE (on the off->digital transition), not re-snapshot
    on every digital->digital hop - re-snapshotting mid-digital would
    capture the narrow digital-era bandwidth instead of the original."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_if_bandwidth(1)

        dev.set_mode("00")  # off -> digital (Auto): snapshot captured (IF1)
        dev._chan.write("IF", "3")  # firmware narrows

        dev.set_mode("10")  # digital -> digital (D-STAR): must NOT re-snapshot
        dev._chan.write("IF", "3")  # still narrow

        dev.set_mode("F0")  # digital -> off: restore the ORIGINAL snapshot
        assert dev.get_if_bandwidth() == "1"


def test_set_mode_leaves_if_bandwidth_alone_for_analog_only_changes():
    """Switching between two analog modes (digital off both times) must
    never touch IF - there's no digital round trip to work around."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")  # FM, digital off
        dev.set_if_bandwidth(2)
        dev.set_mode("F1")  # AM, digital off
        assert dev.get_if_bandwidth() == "2"


def test_set_mode_digital_round_trip_without_if_change_does_not_raise():
    """No IF bandwidth was ever set before going digital - the restore
    step must be a no-op, not an error."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_mode("00")
        dev.set_mode("F0")  # must not raise
