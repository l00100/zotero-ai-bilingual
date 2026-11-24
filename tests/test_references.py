from pathlib import Path
import sys
import tempfile
import unittest

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from references import detect_references, mask_references, restore_references, selected_indexes


def make_paper(path):
    doc = pymupdf.open()
    for number in range(3):
        page = doc.new_page(width=612, height=792)
        for column, left in enumerate((40, 330)):
            for line in range(8):
                page.insert_text((left, 70 + line * 14), f"Body paragraph line {line} keeps its original position.", fontsize=8)
    page = doc[1]
    page.insert_text((380, 250), "REFERENCES", fontsize=11)
    page.insert_text((40, 340), "LEFT BODY BELOW REFERENCES HEADING", fontsize=9)
    for number in range(1, 7):
        page.insert_text((330, 275 + number * 16), f"[{number}] Author. Example research paper title. Journal 2024.", fontsize=8)
    page = doc[2]
    for number in range(7, 12):
        page.insert_text((40, 220 + (number - 7) * 18), f"[{number}] Author. Another research title. Journal 2023.", fontsize=8)
    page.insert_text((40, 400), "APPENDIX A", fontsize=11)
    page.insert_text((40, 430), "APPENDIX BODY MUST BE TRANSLATED", fontsize=9)
    page.insert_text((330, 300), "RIGHT APPENDIX BODY MUST BE TRANSLATED", fontsize=8)
    doc.save(path)
    doc.close()


class ReferenceTests(unittest.TestCase):
    def test_mixed_columns_appendix_and_exact_restore(self):
        with tempfile.TemporaryDirectory(dir=None) as directory:
            folder = Path(directory)
            source, masked, restored = (folder / name for name in ("source.pdf", "masked.pdf", "restored.pdf"))
            make_paper(source)
            path, plan = mask_references(source, masked)
            self.assertEqual(path, masked)
            self.assertEqual(plan.start_page, 2)
            self.assertEqual(len(plan.regions[1]), 1)
            self.assertEqual(plan.regions[1][0][0], 306)
            self.assertEqual(len(plan.regions[2]), 1)
            with pymupdf.open(masked) as doc:
                self.assertNotIn("Example research", doc[1].get_text())
                self.assertNotIn("Another research", doc[2].get_text())
                self.assertIn("LEFT BODY BELOW", doc[1].get_text())
                self.assertIn("APPENDIX BODY MUST", doc[2].get_text())
                self.assertIn("RIGHT APPENDIX BODY", doc[2].get_text())
            restore_references(source, masked, restored, plan)
            with pymupdf.open(source) as original, pymupdf.open(restored) as result:
                for number, regions in plan.regions.items():
                    for region in regions:
                        clip = pymupdf.Rect(region)
                        before = original[number].get_pixmap(clip=clip)
                        after = result[number].get_pixmap(clip=clip)
                        self.assertEqual(before.samples, after.samples)

    def test_page_selection_leaves_outside_references_alone(self):
        with tempfile.TemporaryDirectory(dir=None) as directory:
            folder = Path(directory)
            source = folder / "source.pdf"
            make_paper(source)
            path, plan = mask_references(source, folder / "unused.pdf", "1")
            self.assertEqual(path, source)
            self.assertFalse(plan.regions)
            self.assertEqual(selected_indexes("1,3-", 4), {0, 2, 3})

    def test_ordinary_citations_do_not_trigger_detection(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((50, 80), "We discuss references [1], [2] and the results below.")
        self.assertFalse(detect_references(doc).regions)
        doc.close()



if __name__ == "__main__":
    unittest.main(verbosity=2)
