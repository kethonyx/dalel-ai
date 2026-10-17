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


class ParseChoice(unittest.TestCase):
    OPTS = {"nothing": "nothing", "banknotes": "banknotes", "id_card": "an ID card"}

    def test_letter_maps_to_key(self):
        self.assertEqual(vlm.parse_choice("C", self.OPTS), "id_card")
        self.assertEqual(vlm.parse_choice("B) banknotes", self.OPTS), "banknotes")

    def test_out_of_range_or_garbage_is_unclear(self):
        self.assertEqual(vlm.parse_choice("F", self.OPTS), "unclear")
        self.assertEqual(vlm.parse_choice("hmm", self.OPTS), "unclear")

    def test_prompt_lists_letters(self):
        self.assertIn("C) an ID card", vlm.choice_prompt("What?", self.OPTS))


class ParseYesNo(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(vlm.parse_yes_no("Yes.")["answer"], "yes")
        self.assertEqual(vlm.parse_yes_no("no, it is closed")["answer"], "no")
        self.assertEqual(vlm.parse_yes_no("maybe")["answer"], "unclear")


if __name__ == "__main__":
    unittest.main()
