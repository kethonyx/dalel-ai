"""python -m unittest discover tests"""
import unittest

from app import rules


def tl(*rows, step=1.0):
    return [{"t": i * step, "a": a} for i, a in enumerate(rows)]


STATE = {"id": "s", "type": "T", "kind": "state", "all": {"x": "yes"}, "min_sec": 2}
MISSING = {"id": "m", "type": "M", "kind": "missing_before", "session": {"v": "yes"},
           "trigger": {"h": "yes"}, "missing": {"d": "yes"}}


class StateRule(unittest.TestCase):
    def test_short_run_ignored(self):
        self.assertEqual(rules.evaluate(tl({"x": "yes"}, {"x": "no"}), [STATE]), [])

    def test_run_reported_at_start(self):
        ev = rules.evaluate(tl({"x": "no"}, {"x": "yes"}, {"x": "yes"}, {"x": "no"}), [STATE])
        self.assertEqual([e.t for e in ev], [1.0])

    def test_unasked_probe_does_not_match(self):
        self.assertEqual(rules.evaluate(tl({}, {}, {}), [STATE]), [])


class MissingBefore(unittest.TestCase):
    def test_document_before_trigger_ok(self):
        frames = tl({"v": "yes", "d": "yes"}, {"v": "yes", "h": "yes"})
        self.assertEqual(rules.evaluate(frames, [MISSING]), [])

    def test_no_document_reports_trigger_time(self):
        frames = tl({"v": "no"}, {"v": "yes"}, {"v": "yes", "h": "yes"}, {"v": "yes"})
        self.assertEqual([e.t for e in rules.evaluate(frames, [MISSING])], [2.0])

    def test_document_from_previous_session_does_not_count(self):
        frames = tl({"v": "yes", "d": "yes"}, *[{"v": "no"}] * 5, {"v": "yes"}, {"v": "yes", "h": "yes"})
        self.assertEqual(len(rules.evaluate(frames, [MISSING])), 1)


class Dedupe(unittest.TestCase):
    def test_same_type_close_events_merged(self):
        a = dict(STATE, id="a")
        b = dict(STATE, id="b", all={"y": "yes"})
        frames = tl({"x": "yes", "y": "yes"}, {"x": "yes", "y": "yes"}, {"x": "yes", "y": "yes"})
        self.assertEqual(len(rules.evaluate(frames, [a, b])), 1)


if __name__ == "__main__":
    unittest.main()
