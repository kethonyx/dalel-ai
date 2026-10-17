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

    def test_single_document_frame_not_enough_when_two_required(self):
        rule = dict(MISSING, missing_min_frames=2)
        one = tl({"v": "yes"}, {"v": "yes", "d": "yes"}, {"v": "yes", "h": "yes"})
        two = tl({"v": "yes", "d": "yes"}, {"v": "yes", "d": "yes"}, {"v": "yes", "h": "yes"})
        self.assertEqual(len(rules.evaluate(one, [rule])), 1)
        self.assertEqual(rules.evaluate(two, [rule]), [])

    def test_document_from_previous_session_does_not_count(self):
        frames = tl({"v": "yes", "d": "yes"}, {"v": "yes"}, {"v": "yes"}, *[{"v": "no"}] * 5,
                    {"v": "yes"}, {"v": "yes"}, {"v": "yes", "h": "yes"})
        self.assertEqual(len(rules.evaluate(frames, [MISSING])), 1)


AFTER = {"id": "ma", "type": "MA", "kind": "missing_after", "session": {"v": "yes"},
         "trigger": {"h": "yes"}, "missing": {"m": "yes"}, "window_after_sec": 2}
LEFT = {"id": "as", "type": "AS", "kind": "after_session", "session": {"v": "yes"},
        "require": {"h": "yes"}, "after": {"m": "yes"}, "window_sec": 5, "min_frames": 2}


class MissingAfter(unittest.TestCase):
    def test_counted_after_handover_ok(self):
        frames = tl({"v": "yes", "h": "yes"}, {"v": "yes", "m": "yes"}, {"v": "no"}, {"v": "no"}, {"v": "no"})
        self.assertEqual(rules.evaluate(frames, [AFTER]), [])

    def test_never_counted_reports_handover(self):
        frames = tl({"v": "yes"}, {"v": "yes", "h": "yes"}, {"v": "yes"}, {"v": "no"}, {"v": "no"}, {"v": "no"})
        self.assertEqual([e.t for e in rules.evaluate(frames, [AFTER])], [1.0])

    def test_video_cut_short_is_not_judged(self):
        frames = tl({"v": "yes"}, {"v": "yes", "h": "yes"})
        self.assertEqual(rules.evaluate(frames, [dict(AFTER, window_after_sec=10)]), [])


class AfterSession(unittest.TestCase):
    def test_count_continues_after_client_left(self):
        frames = tl({"v": "yes", "h": "yes"}, {"v": "yes"}, {"v": "yes"}, {"v": "no", "m": "yes"}, {"v": "no", "m": "yes"})
        self.assertEqual([e.t for e in rules.evaluate(frames, [LEFT])], [3.0])

    def test_count_finished_before_leaving_ok(self):
        frames = tl({"v": "yes", "h": "yes"}, {"v": "yes", "m": "yes"}, {"v": "no"}, {"v": "no"})
        self.assertEqual(rules.evaluate(frames, [LEFT]), [])

    def test_no_handover_in_session_ignored(self):
        frames = tl({"v": "yes"}, {"v": "no", "m": "yes"}, {"v": "no", "m": "yes"})
        self.assertEqual(rules.evaluate(frames, [LEFT]), [])


class CoarseToFine(unittest.TestCase):
    def test_even_frames_first_and_indices_kept(self):
        from app import pipeline
        frames = [{"t": float(i)} for i in range(5)]
        self.assertEqual([i for i, _ in pipeline.coarse_to_fine(frames)], [0, 2, 4, 1, 3])
        self.assertTrue(all(fr["t"] == i for i, fr in pipeline.coarse_to_fine(frames)))


class Flicker(unittest.TestCase):
    def test_single_frame_state_ignored_even_with_sparse_frames(self):
        frames = tl({"x": "no"}, {"x": "yes"}, {"x": "no"}, step=2.5)  # один кадр «да» при шаге 2,5 с
        self.assertEqual(rules.evaluate(frames, [STATE]), [])

    def test_visitor_blip_is_not_a_session(self):
        frames = tl({"v": "no"}, {"v": "yes", "h": "yes"}, {"v": "no"}, {"v": "no"})
        self.assertEqual(rules.evaluate(frames, [MISSING]), [])


class Dedupe(unittest.TestCase):
    def test_same_type_close_events_merged(self):
        a = dict(STATE, id="a")
        b = dict(STATE, id="b", all={"y": "yes"})
        frames = tl({"x": "yes", "y": "yes"}, {"x": "yes", "y": "yes"}, {"x": "yes", "y": "yes"})
        self.assertEqual(len(rules.evaluate(frames, [a, b])), 1)


if __name__ == "__main__":
    unittest.main()
