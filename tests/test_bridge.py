"""Bridge integration tests use synthetic PDFs and a fake worker; no paid API."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bridge", ROOT / "service/bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=None)
        self.path = Path(self.temp.name)
        worker = self.path / "fake_worker.py"
        worker.write_text('''import json,sys,time
from pathlib import Path
config=json.load(sys.stdin)
p=Path(sys.argv[1])
if config['model']=='slow':time.sleep(30)
(p/'translated.pdf').write_bytes((p/'source.pdf').read_bytes())
print(json.dumps({'type':'done'}),flush=True)
''', "utf-8")
        self.server = bridge.make_server(self.path / "state", port=0, worker=worker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        for job in list(self.server.jobs.records.values()):
            self.server.jobs.cancel(job)
        self.server.jobs.pool.shutdown(wait=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, auth=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if auth:headers["Authorization"] = "Bearer " + self.server.token
        if origin:headers["Origin"] = origin
        request = Request(self.base + path, data=json.dumps(body).encode() if body else None, headers=headers)
        with urlopen(request, timeout=5) as result:
            return result.status, result.read()

    def payload(self, job_id="a" * 32, model="test"):
        return {"jobID": job_id, "pdf": base64.b64encode(b"%PDF-1.7\nsynthetic fixture").decode(),
                "config": {"baseURL": "https://example.invalid/v1/chat/completions/",
                           "model": model, "apiKey": "synthetic-secret", "pages": "1-2"}}

    def wait_terminal(self, job_id):
        for _ in range(100):
            job = json.loads(self.request("/jobs/" + job_id)[1])
            if job["status"] not in ("queued", "running"):return job
            time.sleep(0.05)
        self.fail("task failed to terminate")

    def test_auth_and_browser_origin(self):
        for auth, origin in [(False, None), (True, "https://example.invalid")]:
            with self.assertRaises(HTTPError) as error:
                self.request("/health", auth=auth, origin=origin)
            self.assertEqual(error.exception.code, 403)
        health = json.loads(self.request("/health")[1])
        self.assertEqual(health["protocol"], 1)

    def test_complete_pdf_recovery_and_no_persisted_key(self):
        payload = self.payload()
        status, raw = self.request("/jobs", payload)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(raw)["id"], "a" * 32)
        job = self.wait_terminal("a" * 32)
        self.assertEqual(job["status"], "completed")
        self.assertTrue(self.request("/jobs/" + job["id"] + "/pdf")[1].startswith(b"%PDF-"))
        saved = (self.path / "state/jobs" / job["id"] / "status.json").read_text("utf-8")
        self.assertNotIn("synthetic-secret", saved)
        self.assertNotIn("apiKey", saved)
        recovered = bridge.Jobs(self.path / "state/jobs")
        self.assertEqual(recovered.records[job["id"]]["status"], "completed")
        recovered.pool.shutdown()

    def test_idempotent_submission_and_cancel(self):
        payload = self.payload("b" * 32, "slow")
        first = json.loads(self.request("/jobs", payload)[1])
        second = json.loads(self.request("/jobs", payload)[1])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.server.jobs.records), 1)
        self.request("/jobs/" + first["id"] + "/cancel", {"cancel": True})
        self.assertEqual(self.wait_terminal(first["id"])["status"], "cancelled")

    def test_invalid_pdf_and_insecure_remote_api(self):
        for change in ["pdf", "url"]:
            payload = self.payload()
            if change == "pdf":payload["pdf"] = "bm90IGEgcGRm"
            else:payload["config"]["baseURL"] = "http://example.invalid/v1"
            with self.assertRaises(HTTPError) as error:self.request("/jobs", payload)
            self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
