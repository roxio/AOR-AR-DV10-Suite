
from aor_dv10.device import DV10Device


def test_set_mode_restores_if_bandwidth_after_digital_round_trip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_if_bandwidth(1)
        assert dev.get_if_bandwidth() == "1"

        dev.set_mode("00")
        dev._chan.write("IF", "3")
        assert dev.get_if_bandwidth() == "3"

        dev.set_mode("F0")
        assert dev.get_if_bandwidth() == "1", (
            "set_mode() should have restored the pre-digital IF bandwidth"
        )


def test_set_mode_does_not_resnapshot_across_digital_to_digital_hops():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_if_bandwidth(1)

        dev.set_mode("00")
        dev._chan.write("IF", "3")

        dev.set_mode("10")
        dev._chan.write("IF", "3")

        dev.set_mode("F0")
        assert dev.get_if_bandwidth() == "1"


def test_set_mode_leaves_if_bandwidth_alone_for_analog_only_changes():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_if_bandwidth(2)
        dev.set_mode("F1")
        assert dev.get_if_bandwidth() == "2"


def test_set_mode_digital_round_trip_without_if_change_does_not_raise():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        dev.set_mode("00")
        dev.set_mode("F0")
