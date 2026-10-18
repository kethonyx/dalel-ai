import unittest

from pipeline.events import expand_box, fill_gaps, find_absences, in_zone

T = [round(i * 0.2, 1) for i in range(40)]  # 5 fps, 8 с


def scale(s: str) -> list[bool]:
    return [c == "1" for c in s]


class FillGaps(unittest.TestCase):
    def test_short_gap_filled(self):
        # провал 3 кадра: от последнего True (0,4 с) до следующего (1,2 с) — 0,8 с
        self.assertEqual(fill_gaps(scale("111000111"), T, 2.0), scale("111111111"))

    def test_long_gap_kept(self):
        v = scale("1" + "0" * 15 + "1")  # 3,2 с между True
        self.assertEqual(fill_gaps(v, T, 2.0), v)

    def test_edges_not_filled(self):
        v = scale("0011100")
        self.assertEqual(fill_gaps(v, T, 2.0), v)


class FindAbsences(unittest.TestCase):
    def test_departure_and_return(self):
        v = scale("1" * 15 + "0" * 15 + "1" * 10)  # занят 2,8 с, пусто 3 с, вернулся
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [(15, 30)])

    def test_short_absence_ignored(self):
        v = scale("1" * 15 + "0" * 5 + "1" * 20)  # пусто 1 с
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [])

    def test_empty_until_end(self):
        v = scale("1" * 33 + "0" * 7)  # пусто последние 1,2 с: меньше min, но больше end_min
        self.assertEqual(find_absences(v, T, 2.0, 2.0, end_min_sec=1.0), [(33, None)])
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [])

    def test_no_departure_before_settling(self):
        # кассир прошёл через зону за 1 с и ушёл к двери — это не уход
        v = scale("0" * 2 + "1" * 5 + "0" * 18 + "1" * 15)
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [])
        # а после того как посидел 2+ с — уход
        v = scale("1" * 12 + "0" * 13 + "1" * 15)
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [(12, 25)])

    def test_empty_start_is_not_departure(self):
        v = scale("0" * 15 + "1" * 25)
        self.assertEqual(find_absences(v, T, 2.0, 2.0), [])


class Geometry(unittest.TestCase):
    def test_in_zone_by_center_or_iou(self):
        zone = (100, 100, 200, 300)
        self.assertTrue(in_zone((120, 150, 180, 250), zone, 0.3))   # центр внутри
        self.assertFalse(in_zone((300, 100, 400, 300), zone, 0.3))  # рядом, без пересечения
        self.assertTrue(in_zone((60, 100, 160, 300), zone, 0.3))    # центр снаружи, IoU 0,33

    def test_expand_clamped_to_frame(self):
        self.assertEqual(expand_box((0, 0, 100, 100), 1.5, 120, 120), (0.0, 0.0, 120.0, 120.0))
        self.assertEqual(expand_box((40, 40, 60, 60), 2.0, 200, 200), (30.0, 30.0, 70.0, 70.0))


if __name__ == "__main__":
    unittest.main()
