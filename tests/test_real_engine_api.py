"""Exercise the real engine's OpenAI translator against a loopback API stub."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from worker import prepare_runtime
prepare_runtime(ROOT / ".test-runtime/data/jobs/test-api")
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import OpenAISettings
from pdf2zh_next.translator import get_translator

calls = []
class MockAPI(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append({"path": self.path, "model": body["model"], "authorized": self.headers.get("Authorization") == "Bearer fixture-key"})
        result = {"id":"fixture", "object":"chat.completion", "created":1, "model":body["model"],
                  "choices":[{"index":0,"message":{"role":"assistant","content":"这是接口测试译文。"},"finish_reason":"stop"}],
                  "usage":{"prompt_tokens":5,"completion_tokens":6,"total_tokens":11}}
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

server = ThreadingHTTPServer(("127.0.0.1", 0), MockAPI)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    settings = SettingsModel(translate_engine_settings=OpenAISettings(
        openai_model="fixture-model", openai_base_url=f"http://127.0.0.1:{server.server_port}/v1",
        openai_api_key="fixture-key", openai_enable_json_mode=False,
        openai_send_temprature=False, openai_send_reasoning_effort=False))
    settings.validate_settings()
    translator = get_translator(settings)
    translated = translator.translate("This is a synthetic API test.", ignore_cache=True)
    assert translated == "这是接口测试译文。", translated
    assert calls and all(call == {"path":"/v1/chat/completions", "model":"fixture-model", "authorized":True} for call in calls), calls
    print("Real PDF2zh-next translator + OpenAI SDK: loopback API translation passed (no external API).")
finally:
    server.shutdown()
    server.server_close()
    thread.join()
