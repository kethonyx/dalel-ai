import unittest

from app import vlm


class Fake:
    def __init__(self, name, alive=True, fail_ask=False):
        self.base_url, self._name, self.alive, self.fail_ask, self.calls = name, name, alive, fail_ask, 0
        self._model_id = None

    @property
    def model_id(self):
        if not self.alive:
            raise vlm.VLMError("down")
        return self._name

    def ask(self, jpeg, q):
        self.calls += 1
        if self.fail_ask:
            raise vlm.VLMError("timeout")
        return {"answer": "yes", "reason": self._name}


class Failover(unittest.TestCase):
    def test_primary_used_when_alive(self):
        fb = vlm.FailoverBackend([Fake("30b"), Fake("8b")])
        self.assertEqual(fb.select(), "30b")
        self.assertEqual(fb.ask(b"", "q")["reason"], "30b")

    def test_dead_primary_skipped_at_select(self):
        fb = vlm.FailoverBackend([Fake("30b", alive=False), Fake("8b")])
        self.assertEqual(fb.select(), "8b")

    def test_switch_mid_video_and_retry_same_request(self):
        primary, backup = Fake("30b", fail_ask=True), Fake("8b")
        fb = vlm.FailoverBackend([primary, backup])
        fb.select()
        self.assertEqual(fb.ask(b"", "q")["reason"], "8b")
        self.assertEqual((primary.calls, backup.calls), (1, 1))
        self.assertEqual(fb.model_id, "8b")
        self.assertEqual(len(fb.switches), 1)

    def test_all_down_raises(self):
        fb = vlm.FailoverBackend([Fake("30b", alive=False), Fake("8b", alive=False)])
        with self.assertRaises(vlm.VLMError):
            fb.select()

    def test_primary_back_on_next_video(self):
        primary = Fake("30b", alive=False)
        fb = vlm.FailoverBackend([primary, Fake("8b")])
        self.assertEqual(fb.select(), "8b")
        primary.alive = True
        self.assertEqual(fb.select(), "30b")


if __name__ == "__main__":
    unittest.main()
