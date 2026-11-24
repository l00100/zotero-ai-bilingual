"""Isolated layout worker; credentials arrive through stdin, never command args."""
from __future__ import annotations
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading

_emit_lock = threading.Lock()
STAGE_LABELS = {
    "Parse PDF and Create Intermediate Representation": "解析 PDF",
    "DetectScannedFile": "检查扫描页",
    "Parse Page Layout": "分析版面",
    "Parse Table": "识别表格",
    "Parse Paragraphs": "识别段落",
    "Parse Formulas and Styles": "识别公式与样式",
    "Automatic Term Extraction": "提取术语",
    "Translate Paragraphs": "AI 翻译段落",
    "Typesetting": "排版译文",
    "Add Fonts": "嵌入字体",
    "Generate drawing instructions": "生成 PDF 绘制指令",
    "Subset Fonts": "优化字体",
    "Save PDF": "保存译文 PDF",
}


def emit(event):
    with _emit_lock:
        print(json.dumps(event, ensure_ascii=False), flush=True)


def progress_event(event):
    """Ignore summaries, which otherwise look like a stalled zero-percent job."""
    if event.get("type") not in ("progress_start", "progress_update", "progress_end"):
        return None
    try:
        progress = max(0, min(99, float(event.get("overall_progress", 0))))
    except (TypeError, ValueError):
        progress = 0
    stage = str(event.get("stage", "正在处理 PDF"))
    message = STAGE_LABELS.get(stage, stage)[:100]
    current, total = event.get("stage_current"), event.get("stage_total")
    if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total > 0:
        message += f" · {current:g}/{total:g}"
    return {"type": "progress", "progress": progress, "message": message}


class InitializationProgress:
    def __init__(self, runtime):
        self.runtime = runtime
        self.cache = runtime / ".cache" / "babeldoc" if sys.platform == "win32" else Path.home() / ".cache" / "babeldoc"
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.monitor, daemon=True)

    def monitor(self):
        while not self.stop_event.is_set():
            try:
                cache = self.cache
                files = [file for subdir in ("models", "fonts", "cmap", "tiktoken")
                         for file in (cache / subdir).rglob("*") if file.is_file()]
                size = sum(file.stat().st_size for file in files) / (1024 * 1024)
                emit({"type": "progress", "progress": 0,
                      "message": f"准备模型和字体 / 检查 AI 连接 · 已缓存 {len(files)} 个文件，{size:.0f} MB（首次运行需下载）"})
            except OSError:
                pass
            self.stop_event.wait(5)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join()


def prepare_runtime(folder):
    # These libraries hard-code Path.home(); give only this worker process an
    # isolated profile so caches/config stay inside the installed service data.
    runtime = folder.parent.parent / "engine-home"
    runtime.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.environ["USERPROFILE"] = str(runtime)
    os.environ["HF_HOME"] = str(runtime / "huggingface")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    return runtime


async def translate(folder, config):
    runtime = prepare_runtime(folder)
    initialization = InitializationProgress(runtime)
    initialization.start()
    try:
        await translate_document(folder, config, initialization)
    finally:
        initialization.stop()


async def translate_document(folder, config, initialization):
    logging.disable(logging.CRITICAL)
    # Force loky to use its cached CPU count, avoiding visible PowerShell windows.
    try:
        import joblib.externals.loky.backend.context as loky
        loky.physical_cores_cache = os.cpu_count()
    except ImportError:
        pass
    from pdf2zh_next.config.model import SettingsModel, TranslationSettings, PDFSettings, BasicSettings
    from pdf2zh_next.config.translate_engine_model import OpenAISettings
    from pdf2zh_next.high_level import create_babeldoc_config
    from babeldoc.format.pdf.high_level import async_translate

    original_source = folder / "source.pdf"
    source = original_source
    reference_plan = None
    if config.get("skipReferences", True):
        from references import mask_references
        source, reference_plan = mask_references(original_source, folder / "translation-input.pdf", config["pages"])
        if reference_plan.regions:
            emit({"type": "progress", "progress": 0,
                  "message": f"已识别第 {reference_plan.start_page} 页起的参考文献，将保留原文"})
        elif reference_plan.start_page is None:
            emit({"type": "progress", "progress": 0,
                  "message": "未可靠识别参考文献标题，将按所选页码翻译"})

    settings = SettingsModel(
        basic=BasicSettings(debug=False),
        translation=TranslationSettings(
            lang_in=config["sourceLang"], lang_out=config["targetLang"],
            output=str(folder / "output"), qps=config["qps"],
            pool_max_workers=config["qps"], no_auto_extract_glossary=True,
        ),
        pdf=PDFSettings(no_dual=True, no_mono=False, pages=config["pages"] or None,
                        watermark_output_mode="no_watermark",
                        translate_table_text=config["translateTables"]),
        translate_engine_settings=OpenAISettings(
            openai_model=config["model"], openai_base_url=config["baseURL"],
            openai_api_key=config["apiKey"], openai_timeout="120",
            openai_enable_json_mode=False, openai_send_temprature=False,
            openai_send_reasoning_effort=False,
        ),
    )
    settings.validate_settings()
    # Use the same engine directly inside this isolated worker, with debug
    # artifacts disabled. Killing this worker still cancels the whole job.
    engine_config = create_babeldoc_config(settings, source)
    finished = False
    async for event in async_translate(engine_config):
        kind = event.get("type")
        if kind == "error":
            raise RuntimeError(str(event.get("error", "翻译失败")))
        if kind == "finish":
            initialization.stop()
            result = event["translate_result"]
            if not result.mono_pdf_path:
                raise RuntimeError("排版引擎没有返回单语译文 PDF")
            if ".debug." in Path(result.mono_pdf_path).name:
                raise RuntimeError("排版引擎返回了调试版 PDF，已阻止保存带调试标记的译文")
            if reference_plan and reference_plan.regions:
                from references import restore_references
                restore_references(original_source, result.mono_pdf_path, folder / "translated.pdf", reference_plan)
            else:
                shutil.copyfile(result.mono_pdf_path, folder / "translated.pdf")
            finished = True
            break
        update = progress_event(event)
        if update:
            initialization.stop()
            emit(update)
    if not finished:
        raise RuntimeError("翻译未正常完成")
    emit({"type": "done"})


if __name__ == "__main__":
    config = {}
    try:
        config = json.load(sys.stdin)
        asyncio.run(translate(Path(sys.argv[1]).resolve(), config))
    except Exception as exc:
        message = str(exc)
        if config.get("apiKey"):
            message = message.replace(config["apiKey"], "[已隐藏密钥]")
        emit({"type": "error", "message": message[:500]})
        sys.exit(1)
