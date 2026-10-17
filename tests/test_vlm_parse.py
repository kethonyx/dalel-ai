import unittest

from app import vlm


class ParseBoxes(unittest.TestCase):
    def test_degenerate_repeated_output_keeps_first_box(self):
        bad = '[{"label": "desk", "bbox_2d": [100, 400, 700, 600], "bbox_2d": [0, 0, 5, 5], "bbox_2'
        boxes = vlm.parse_boxes(bad, 1, 1)
        self.assertEqual(boxes[0]["label"], "desk")
        self.assertEqual(boxes[0]["box"], (0.1, 0.4, 0.7, 0.6))

    def test_empty_box_means_not_found(self):
        self.assertEqual(vlm.parse_boxes('{"bbox_2d": []}', 1, 1), [])


class ParseYesNo(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(vlm.parse_yes_no("Yes.")["answer"], "yes")
        self.assertEqual(vlm.parse_yes_no("no, it is closed")["answer"], "no")
        self.assertEqual(vlm.parse_yes_no("maybe")["answer"], "unclear")


if __name__ == "__main__":
    unittest.main()
