"""Loopback-only PDF2zh-next bridge. No API credentials are written to disk."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hmac
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_PDF = 100 * 1024 * 1024
MAX_BODY = MAX_PDF * 4 // 3 + 65536
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


def validate_config(raw):
    endpoint = str(raw.get("baseURL", "")).strip().rstrip("/")
    endpoint = re.sub(r"/chat/completions$", "", endpoint)
    url = urlsplit(endpoint)
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("请填写不含密钥或查询参数的 API Base URL")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("远程 AI 接口必须使用 HTTPS；本机接口可以使用 HTTP")
    model = str(raw.get("model", "")).strip()
    key = str(raw.get("apiKey", "")).strip()
    if not model or not key:
        raise ValueError("请先填写模型名称和 API Key（无密钥的本地接口可填 local）")
    source = str(raw.get("sourceLang", "en")).strip()
    target = str(raw.get("targetLang", "zh")).strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,20}", source + "") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,20}", target):
        raise ValueError("无效的语言代码")
    pages = str(raw.get("pages", "")).strip()
    if pages and not re.fullmatch(r"[0-9,\- ]{1,200}", pages):
        raise ValueError("页码请填写 1-3 或 1,3,5 这样的范围")
    return {"baseURL": endpoint, "model": model, "apiKey": key,
            "sourceLang": source, "targetLang": target, "pages": pages,
            "qps": max(1, min(4, int(raw.get("qps", 2)))),
            "translateTables": bool(raw.get("translateTables", False)),
            "skipReferences": raw.get("skipReferences", True) is not False}


def decode_pdf(value):
    if not isinstance(value, str):
        raise ValueError("缺少 PDF 文件内容")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("无效的 PDF 编码") from exc
    if not data.startswith(b"%PDF-") or len(data) > MAX_PDF:
        raise ValueError("仅接受有效 PDF，最大 100 MB")
    return data


class Jobs:
    def __init__(self, state_dir, worker=None):
        self.root = Path(state_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.records = {}
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.worker = worker or Path(__file__).with_name("worker.py")
        # Recover completed outputs after service restart, without credentials.
        for record in self.root.glob("*/status.json"):
            try:
                job = json.loads(record.read_text("utf-8"))
                if job["status"] not in ("completed", "failed", "cancelled"):
                    job.update(status="failed", message="服务已重启；请重新提交翻译")
                self.records[job["id"]] = job
            except (OSError, ValueError, KeyError):
                continue

    def public(self, job):
        return {k: v for k, v in job.items() if k not in ("process", "cancel")}

    def update(self, job, **changes):
        with self.lock:
            job.update(changes)
            path = self.root / job["id"] / "status.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.public(job), ensure_ascii=False), "utf-8")
            temporary.replace(path)

    def submit(self, payload):
        request_id = str(payload.get("jobID", ""))
        if not JOB_ID.fullmatch(request_id):
            raise ValueError("缺少有效任务 ID")
        with self.lock:
            if request_id in self.records:
                return self.public(self.records[request_id])
        config = validate_config(payload.get("config", {}))
        data = decode_pdf(payload.get("pdf"))
        with self.lock:
            if sum(j["status"] in ("queued", "running") for j in self.records.values()) >= 10:
                raise ValueError("队列已有 10 个任务，请等待完成后再提交")
            if request_id in self.records:
                return self.public(self.records[request_id])
            job_id = request_id
            folder = self.root / job_id
            folder.mkdir()
            (folder / "source.pdf").write_bytes(data)
            job = {"id": job_id, "status": "queued", "progress": 0,
                   "message": "等待本地排版引擎", "createdAt": time.time()}
            self.records[job_id] = job
            self.update(job)
        self.pool.submit(self.run, job, config)
        return self.public(job)

    def run(self, job, config):
        folder = self.root / job["id"]
        process = None
        try:
            with self.lock:
                if job["status"] == "cancelled":
                    return
                self.update(job, status="running", message="正在准备排版模型；首次使用可能需要下载模型和字体")
            process = subprocess.Popen(
                [sys.executable, "-u", str(self.worker), str(folder)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self.lock:
                job["process"] = process
                if job["status"] == "cancelled":
                    process.terminate()
                    return
            process.stdin.write(json.dumps(config, ensure_ascii=False))
            process.stdin.close()
            config.clear()
            watchdog = threading.Timer(3 * 3600, process.terminate)
            watchdog.daemon = True
            watchdog.start()
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "progress":
                        self.update(job, progress=max(0, min(99, float(event.get("progress", 0)))),
                                    message=str(event.get("message", "正在翻译"))[:200])
                    elif event.get("type") == "error":
                        raise RuntimeError(str(event.get("message", "翻译失败")))
                returncode = process.wait()
            finally:
                watchdog.cancel()
            if job["status"] == "cancelled":
                return
            output = folder / "translated.pdf"
            if returncode or not output.is_file() or not output.read_bytes().startswith(b"%PDF-"):
                raise RuntimeError("翻译引擎未生成有效译文。请检查接口设置、模型可用性及首次模型下载网络。")
            self.update(job, status="completed", progress=100, message="译文已生成")
        except Exception as exc:
            if job["status"] != "cancelled":
                self.update(job, status="failed", message=str(exc)[:500])
        finally:
            config.clear()
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            if process is not None:
                if process.stdout: process.stdout.close()
                if process.stdin and not process.stdin.closed: process.stdin.close()
            job.pop("process", None)

    def cancel(self, job):
        with self.lock:
            if job["status"] in ("queued", "running"):
                self.update(job, status="cancelled", message="任务已取消")
                process = job.get("process")
                if process and process.poll() is None:
                    process.terminate()
            return self.public(job)


class Handler(BaseHTTPRequestHandler):
    server_version = "HJFY-AI-Reader/1"

    def log_message(self, *_args):
        pass  # Never log payloads, API keys or paper contents.

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Origin") or not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + self.server.token
        ):
            self.reply(403, {"message": "本地服务认证失败"})
            return False
        return True

    def route(self, method):
        if not self.authorized():
            return
        route = urlsplit(self.path).path.strip("/").split("/")
        try:
            if method == "GET" and route == ["health"]:
                self.reply(200, {"status": "ok", "protocol": 1,
                                 "engine": "PDF2zh-next " + importlib.metadata.version("pdf2zh-next")})
                return
            if method == "POST" and route == ["jobs"]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.reply(413, {"message": "PDF 请求过大或为空"})
                    return
                payload = json.loads(self.rfile.read(length))
                self.reply(202, self.server.jobs.submit(payload))
                return
            if len(route) in (2, 3) and route[0] == "jobs" and JOB_ID.fullmatch(route[1]):
                job = self.server.jobs.records.get(route[1])
                if not job:
                    self.reply(404, {"message": "任务不存在；服务可能已清理缓存"})
                    return
                if method == "GET" and len(route) == 2:
                    self.reply(200, self.server.jobs.public(job))
                    return
                if method == "POST" and route[2:] == ["cancel"]:
                    self.reply(200, self.server.jobs.cancel(job))
                    return
                if method == "GET" and route[2:] == ["pdf"] and job["status"] == "completed":
                    path = self.server.jobs.root / job["id"] / "translated.pdf"
                    data = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.reply(404, {"message": "未知请求或任务尚未完成"})
        except (ValueError, TypeError) as exc:
            self.reply(400, {"message": str(exc)[:300]})
        except Exception:
            self.reply(500, {"message": "本地翻译服务处理失败"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


def make_server(state_dir, port=8891, worker=None):
    state = Path(state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    token_path = state / "bridge-token.txt"
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), "ascii")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.token = token_path.read_text("ascii").strip()
    server.jobs = Jobs(state / "jobs", worker)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--port", type=int, default=8891)
    args = parser.parse_args()
    make_server(args.state_dir, args.port).serve_forever()
