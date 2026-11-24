"""No-network tests for worker stages and the non-debug engine adapter."""
import asyncio
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
import worker


class WorkerTests(unittest.TestCase):
    def test_summary_does_not_replace_stage(self):
        self.assertIsNone(worker.progress_event({"type":"stage_summary"}))

    def test_stage_label_counters_and_progress(self):
        result = worker.progress_event({"type":"progress_update", "stage":"Translate Paragraphs",
                                        "stage_current":3,"stage_total":10,"overall_progress":62.5})
        self.assertEqual(result["message"], "AI 翻译段落 · 3/10")
        self.assertEqual(result["progress"], 62.5)

    def test_non_debug_adapter_preserves_pages_and_result(self):
        with tempfile.TemporaryDirectory(dir=None) as temporary:
            folder = Path(temporary) / "data/jobs/fixture"
            folder.mkdir(parents=True)
            (folder / "source.pdf").write_bytes(b"%PDF-1.7\nsynthetic source")
            output = folder / "result.pdf"
            output.write_bytes(b"%PDF-1.7\nsynthetic result")
            worker.prepare_runtime(folder)
            import pdf2zh_next.high_level as high_level
            import babeldoc.format.pdf.high_level as engine
            seen = []
            def create(settings, source):
                self.assertFalse(settings.basic.debug)
                self.assertEqual(settings.pdf.pages, "1-2")
                self.assertEqual(source, folder / "source.pdf")
                seen.append(True)
                return object()
            async def translate(_config):
                yield {"type":"progress_update","stage":"Typesetting","overall_progress":95}
                yield {"type":"finish","translate_result":SimpleNamespace(mono_pdf_path=output)}
            config = {"sourceLang":"en","targetLang":"zh","qps":2,"pages":"1-2",
                      "translateTables":False,"skipReferences":False,"model":"fixture","baseURL":"http://localhost:1/v1","apiKey":"fixture"}
            with patch.object(high_level, "create_babeldoc_config", create), patch.object(engine, "async_translate", translate):
                with redirect_stdout(io.StringIO()):
                    asyncio.run(worker.translate(folder, config))
            self.assertTrue(seen)
            self.assertEqual((folder / "translated.pdf").read_bytes(), output.read_bytes())
            import babeldoc.translator.cache as babel_cache
            import pdf2zh_next.translator.cache as next_cache
            babel_cache.db.close()
            next_cache.db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
