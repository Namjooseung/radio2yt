"""app.youtube를 가짜 Google 서버로 점검한다 (로그인 → 암호화 저장 → 이어 올리기, 중간 503 한 번).

    .venv\\Scripts\\python -m unittest tests.test_youtube
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ["APPDATA"] = tempfile.mkdtemp()  # 실제 사용자 데이터를 건드리지 않는다
from app import youtube  # noqa: E402


class FakeGoogle(BaseHTTPRequestHandler):
    received = bytearray()
    fail_once = True
    meta = None

    def _send(self, code, body=None, headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        data = json.dumps(body).encode() if body is not None else b""
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # 채널 조회
        assert self.headers["Authorization"] == "Bearer ACCESS"
        self._send(200, {"items": [{"snippet": {"title": "SoneFM 테스트"}}]})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/token":
            f = urllib.parse.parse_qs(body.decode())
            if f["grant_type"] == ["authorization_code"]:
                assert f["code"] == ["CODE"] and f["code_verifier"][0]
            else:
                assert f["refresh_token"] == ["REFRESH"]
            self._send(200, {"access_token": "ACCESS", "refresh_token": "REFRESH"})
        elif self.path.startswith("/upload"):
            FakeGoogle.meta = json.loads(body)
            self._send(200, headers=[("Location", f"http://127.0.0.1:{self.server.server_port}/session")])

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        rng = self.headers["Content-Range"]
        total = int(rng.rsplit("/", 1)[1])
        if not rng.startswith("bytes */"):
            if FakeGoogle.fail_once and FakeGoogle.received:  # 두 번째 조각에서 한 번 실패
                FakeGoogle.fail_once = False
                return self._send(503, {"error": {"message": "busy"}})
            start = int(rng.split()[1].split("-")[0])
            assert start == len(FakeGoogle.received)
            FakeGoogle.received += body
        if len(FakeGoogle.received) == total:
            return self._send(201, {"id": "VIDEO123"})
        self._send(308, headers=[("Range", f"bytes=0-{len(FakeGoogle.received) - 1}")])

    def log_message(self, *_):
        pass


class YoutubeTest(unittest.TestCase):
    def test_login_and_upload(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"

        def fake_browser(url):  # 사용자가 로그인하고 Google이 돌려보내는 것을 흉내 낸다
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            assert q["code_challenge_method"] == ["S256"]
            back = f"{q['redirect_uri'][0]}/?state={q['state'][0]}&code=CODE"
            threading.Thread(target=lambda: urllib.request.urlopen(back).read(), daemon=True).start()

        data = os.urandom(youtube.CHUNK * 2 + 12345)
        mp4 = Path(os.environ["APPDATA"]) / "v.mp4"
        mp4.write_bytes(data)
        with mock.patch.multiple(youtube, TOKEN_URL=base + "/token", CHANNEL_URL=base + "/channels",
                                 UPLOAD_URL=base + "/upload?x=1", REVOKE_URL=base + "/token"), \
                mock.patch.object(youtube, "client", return_value={"client_id": "I", "client_secret": "S"}), \
                mock.patch("webbrowser.open", fake_browser), mock.patch("time.sleep"):
            self.assertEqual(youtube.login(), "SoneFM 테스트")
            self.assertEqual(youtube.account(), "SoneFM 테스트")
            self.assertNotIn(b"REFRESH", youtube._login_path().read_bytes())  # 암호화되어 있다
            seen = []
            self.assertEqual(youtube.upload(str(mp4), "제목", "설명", progress=seen.append), "VIDEO123")
        self.assertEqual(bytes(FakeGoogle.received), data)
        self.assertEqual(FakeGoogle.meta["status"]["privacyStatus"], "public")
        self.assertEqual(FakeGoogle.meta["snippet"]["title"], "제목")
        self.assertTrue(seen and seen == sorted(seen))
        self.assertFalse(FakeGoogle.fail_once)  # 503 뒤 이어 올리기를 거쳤다
        srv.shutdown()
        srv.server_close()

    def test_check_text(self):
        self.assertIsNone(youtube.check_text("교육공감 56화", "설명"))
        self.assertTrue(youtube.check_text(" ", ""))
        self.assertTrue(youtube.check_text("a" * 101, ""))
        self.assertTrue(youtube.check_text("a<b", ""))
        self.assertTrue(youtube.check_text("a", "가" * 1700))


if __name__ == "__main__":
    unittest.main()
