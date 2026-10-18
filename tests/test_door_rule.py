import unittest

from app import rules

DOOR = {"id": "door_open", "type": "D", "kind": "signal", "signal": "door", "threshold": 0.1, "min_sec": 4,
        "max_shift_px": 4}


def sig(ds, light=None, shift=0.0):
    light = light or [1.0] * len(ds)
    return {"door": {"rows": [{"t": i * 0.5, "d": d, "light": l} for i, (d, l) in enumerate(zip(ds, light))],
                     "max_shift": shift}}


class DoorSignal(unittest.TestCase):
    def test_sustained_change_reported_at_start(self):
        ev = rules.evaluate([], [DOOR], signals=sig([0] * 4 + [0.2] * 10))
        self.assertEqual([e.t for e in ev], [2.0])

    def test_person_passing_is_short(self):
        self.assertEqual(rules.evaluate([], [DOOR], signals=sig([0] * 4 + [0.3] * 5 + [0] * 4)), [])

    def test_lights_off_breaks_run(self):
        self.assertEqual(rules.evaluate([], [DOOR], signals=sig([0.5] * 10, light=[0.4] * 10)), [])

    def test_handheld_camera_skipped(self):
        self.assertEqual(rules.evaluate([], [DOOR], signals=sig([0.5] * 20, shift=12.0)), [])

    def test_no_signal(self):
        self.assertEqual(rules.evaluate([], [DOOR]), [])


if __name__ == "__main__":
    unittest.main()
