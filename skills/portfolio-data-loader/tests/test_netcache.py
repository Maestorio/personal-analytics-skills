#!/usr/bin/env python3
"""API-1b PR-2: netcache — запись и повтор ответов сети для сверки «скилл против скрипта».

Контракт:
  • record: настоящий запрос; тело, статус и заголовки ответа — в каталог пакета;
  • replay: ответ из каталога; сеть не трогается никогда (нет записи → URLError с адресом,
    а не тихий поход в сеть — иначе сверка «на тех же ответах» молча врёт);
  • порядок параметров запроса не меняет ключ; тело POST — меняет;
  • HTTP-ошибка (4xx/5xx) записывается и повторяется как HTTPError — фолбэки скриптов
    при повторе срабатывают так же, как при записи;
  • gzip-ответ (moex_quotes, fetch_macro) повторяется байт в байт с Content-Encoding.

Сеть — локальный http.server в потоке, внешних запросов нет.
Запуск: python3 skills/portfolio-data-loader/tests/test_netcache.py
"""
import gzip
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import netcache  # noqa: E402


class _H(http.server.BaseHTTPRequestHandler):
    hits = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _H.hits += 1
        if self.path.startswith("/fail"):
            self._send(503, b"down")
        elif self.path.startswith("/gz"):
            self._send(200, gzip.compress(b'{"gz": true}'), [("Content-Encoding", "gzip"),
                                                               ("Content-Type", "application/json")])
        else:
            self._send(200, json.dumps({"path": self.path}).encode(), [("Content-Type", "application/json")])

    def do_POST(self):
        _H.hits += 1
        n = int(self.headers.get("Content-Length", 0))
        self._send(200, b"posted:" + self.rfile.read(n))


class NetcacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._orig = urllib.request.urlopen
        # Прокси окружения не должен перехватывать 127.0.0.1
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

    def tearDown(self):
        urllib.request.urlopen = self._orig

    def _get(self, url, data=None):
        with urllib.request.urlopen(url, data=data, timeout=5) as r:
            return r.read(), r.status, r.headers

    def test_record_then_replay_without_network(self):
        netcache.install("record", self.dir)
        body, status, _ = self._get(self.base + "/a?x=1&y=2")
        urllib.request.urlopen = self._orig
        netcache.install("replay", self.dir)
        hits = _H.hits
        body2, status2, _ = self._get(self.base + "/a?y=2&x=1")   # другой порядок параметров
        self.assertEqual((body, status), (body2, status2))
        self.assertEqual(_H.hits, hits, "replay ходил в сеть")

    def test_replay_miss_raises_urlerror(self):
        netcache.install("record", self.dir)
        urllib.request.urlopen = self._orig
        netcache.install("replay", self.dir)
        with self.assertRaises(urllib.error.URLError) as cm:
            self._get(self.base + "/never")
        self.assertIn("/never", str(cm.exception))

    def test_replay_requires_index(self):
        with self.assertRaises(FileNotFoundError):
            netcache.install("replay", self.dir)

    def test_http_error_recorded_and_replayed(self):
        netcache.install("record", self.dir)
        with self.assertRaises(urllib.error.HTTPError):
            self._get(self.base + "/fail")
        urllib.request.urlopen = self._orig
        netcache.install("replay", self.dir)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get(self.base + "/fail")
        self.assertEqual(cm.exception.code, 503)

    def test_gzip_bytes_and_header_preserved(self):
        netcache.install("record", self.dir)
        raw, _, h = self._get(self.base + "/gz")
        urllib.request.urlopen = self._orig
        netcache.install("replay", self.dir)
        raw2, _, h2 = self._get(self.base + "/gz")
        self.assertEqual(raw, raw2)
        self.assertEqual(h2.get("Content-Encoding"), "gzip")
        self.assertEqual(json.loads(gzip.decompress(raw2)), {"gz": True})

    def test_post_body_is_part_of_key(self):
        netcache.install("record", self.dir)
        self._get(urllib.request.Request(self.base + "/p", data=b"A"))
        urllib.request.urlopen = self._orig
        netcache.install("replay", self.dir)
        self.assertEqual(self._get(urllib.request.Request(self.base + "/p", data=b"A"))[0], b"posted:A")
        with self.assertRaises(urllib.error.URLError):
            self._get(urllib.request.Request(self.base + "/p", data=b"B"))

    def test_cli_run_wraps_script(self):
        script = os.path.join(self.dir, "s.py")
        with open(script, "w") as f:
            f.write("import sys, urllib.request\n"
                    "print(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode())\n")
        net = os.path.join(self.dir, "net")
        env = dict(os.environ)
        cmd = [sys.executable, os.path.join(SCRIPTS, "netcache.py"), "run"]
        out1 = subprocess.run(cmd + ["--record", net, "--", script, self.base + "/cli"],
                              capture_output=True, text=True, env=env, check=True).stdout
        out2 = subprocess.run(cmd + ["--replay", net, "--", script, self.base + "/cli"],
                              capture_output=True, text=True, env=env, check=True).stdout
        self.assertEqual(out1, out2)
        self.assertIn("/cli", out2)

    def test_record_creates_empty_index(self):
        netcache.install("record", self.dir)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "index.json")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
