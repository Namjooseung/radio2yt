"""유튜브 업로드: Google 로그인(데스크톱 앱 OAuth, PKCE)과 이어 올리기(resumable) 업로드.

표준 라이브러리만 쓴다. 로그인 정보(refresh token)는 Windows DPAPI로 암호화해서
사용자 폴더에 둔다 — 같은 Windows 계정에서만 풀 수 있다.
Google 연결 설정 파일은 assets/client_secret.json (저장소에는 올리지 않는다).
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import http.server
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

from engine.pipeline import Cancelled
from . import store
from .theme import assets_dir

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
PRIVACY = "public"          # 사용자 결정. Google 앱 심사 전에는 YouTube가 비공개로 잠근다
CHUNK = 8 * 1024 * 1024     # 256KB의 배수여야 한다
LOGIN_TIMEOUT = 300
RETRIES = 5

MESSAGES = {
    "invalid_grant": "로그인이 만료되었습니다. 다시 로그인하세요.",
    "quotaExceeded": "오늘 쓸 수 있는 업로드 횟수를 넘었습니다. 내일 다시 시도하세요.",
    "uploadLimitExceeded": "이 채널의 업로드 한도를 넘었습니다. 나중에 다시 시도하세요.",
    "youtubeSignupRequired": "이 계정에는 유튜브 채널이 없습니다.",
    "invalidTitle": "제목에 쓸 수 없는 내용이 있습니다.",
    "invalidDescription": "설명에 쓸 수 없는 내용이 있습니다.",
}


class ApiError(RuntimeError):
    def __init__(self, e: urllib.error.HTTPError):
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        err = body.get("error")
        if isinstance(err, dict):   # YouTube API 형식
            self.reason = (err.get("errors") or [{}])[0].get("reason", "")
            msg = err.get("message", "")
        else:                       # OAuth 형식
            self.reason, msg = err or "", body.get("error_description", "")
        super().__init__(MESSAGES.get(self.reason) or f"Google 서버 오류 ({e.code}) {msg}".strip())


def _open(req: urllib.request.Request, timeout: float = 60):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise ApiError(e) from None
    except OSError as e:
        raise RuntimeError(f"Google에 연결하지 못했습니다. 인터넷 연결을 확인하세요.\n{e}") from None


def _json(req: urllib.request.Request) -> dict:
    with _open(req) as r:
        return json.loads(r.read())


def _post_form(url: str, fields: dict) -> dict:
    return _json(urllib.request.Request(url, urllib.parse.urlencode(fields).encode()))


def client() -> dict:
    p = assets_dir() / "client_secret.json"
    try:
        c = json.loads(p.read_text(encoding="utf-8"))["installed"]
        return {"client_id": c["client_id"], "client_secret": c["client_secret"]}
    except (OSError, ValueError, KeyError):
        raise RuntimeError("Google 연결 설정 파일(client_secret.json)이 없거나 형식이 맞지 않습니다.\n"
                           "프로그램 관리자에게 문의하세요.") from None


# ── 로그인 정보 저장 (DPAPI) ──
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _login_path() -> Path:
    return store.data_dir() / "youtube_login.bin"


def _load() -> dict | None:
    try:
        return json.loads(_dpapi(_login_path().read_bytes(), protect=False))
    except (OSError, ValueError):
        return None


def account() -> str | None:
    """로그인된 유튜브 채널 이름. 로그인하지 않았으면 None."""
    s = _load()
    return s.get("channel") if s else None


def logout() -> None:
    s = _load()
    _login_path().unlink(missing_ok=True)
    if s:
        try:  # 이 PC에서 지워도 Google 쪽 권한이 남지 않게 취소한다 (실패해도 로그아웃은 된 것)
            _post_form(REVOKE_URL, {"token": s["refresh_token"]})
        except RuntimeError:
            pass


# ── 로그인 ──
def login(is_cancelled=lambda: False) -> str:
    """브라우저로 Google 로그인을 받고 채널 이름을 돌려준다."""
    c = client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 5  # 브라우저가 미리 열어 두고 요청을 안 보내는 연결 때문에 멈추지 않게

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] != state:   # favicon 등 다른 요청은 무시
                self.send_response(404)
                self.end_headers()
                return
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "로그인을 마쳤습니다." if "code" in got else "로그인하지 않았습니다."
            self.wfile.write(f"<p style='font:16px sans-serif'>{msg} 이 창을 닫고 프로그램으로 돌아가세요.</p>".encode())

        def log_message(self, *_):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    srv.timeout = 0.5
    redirect = f"http://127.0.0.1:{srv.server_port}"
    try:
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": SCOPES, "code_challenge": challenge, "code_challenge_method": "S256",
            "state": state, "access_type": "offline", "prompt": "consent"}))
        deadline = time.time() + LOGIN_TIMEOUT
        while "code" not in got and "error" not in got:
            if is_cancelled():
                raise Cancelled()
            if time.time() > deadline:
                raise RuntimeError("로그인 시간이 지났습니다. 다시 시도하세요.")
            srv.handle_request()
    finally:
        srv.server_close()
    if "error" in got:
        raise RuntimeError("Google 로그인을 취소했습니다." if got["error"] == "access_denied"
                           else f"Google 로그인에 실패했습니다. ({got['error']})")

    tok = _post_form(TOKEN_URL, {**c, "code": got["code"], "code_verifier": verifier,
                                 "redirect_uri": redirect, "grant_type": "authorization_code"})
    req = urllib.request.Request(CHANNEL_URL, headers={"Authorization": f"Bearer {tok['access_token']}"})
    items = _json(req).get("items") or []
    if not items:
        raise RuntimeError(MESSAGES["youtubeSignupRequired"])
    channel = items[0]["snippet"]["title"]
    data = json.dumps({"refresh_token": tok["refresh_token"], "channel": channel}).encode()
    _login_path().write_bytes(_dpapi(data, protect=True))
    return channel


def _access_token() -> str:
    s = _load()
    if not s:
        raise RuntimeError("먼저 Google 계정으로 로그인하세요.")
    try:
        return _post_form(TOKEN_URL, {**client(), "refresh_token": s["refresh_token"],
                                      "grant_type": "refresh_token"})["access_token"]
    except ApiError as e:
        if e.reason == "invalid_grant":  # 사용자가 권한을 취소했거나 오래되어 만료됨
            _login_path().unlink(missing_ok=True)
        raise


# ── 업로드 ──
def check_text(title: str, description: str) -> str | None:
    """YouTube가 거부하는 제목·설명이면 이유를 돌려준다."""
    if not title.strip():
        return "제목을 입력하세요."
    if len(title) > 100:
        return f"제목은 100자까지 쓸 수 있습니다. (지금 {len(title)}자)"
    if len(description.encode("utf-8")) > 5000:
        return "설명이 너무 깁니다. 한글 기준 약 1,600자까지 쓸 수 있습니다."
    if any(ch in title + description for ch in "<>"):
        return "제목과 설명에는 < > 기호를 쓸 수 없습니다."
    return None


def upload(path: str, title: str, description: str, progress=None, is_cancelled=lambda: False) -> str:
    """mp4를 올리고 영상 ID를 돌려준다. 끊기면 올린 데까지 확인하고 이어서 올린다."""
    # shortcut: 토큰을 한 번만 받는다(1시간 유효). 한 영상 업로드가 1시간을 넘기는 회선이면 갱신을 추가한다
    auth = {"Authorization": f"Bearer {_access_token()}"}
    size = Path(path).stat().st_size
    meta = {"snippet": {"title": title, "description": description, "categoryId": "22"},
            "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False}}
    req = urllib.request.Request(UPLOAD_URL, json.dumps(meta).encode(), headers={
        **auth, "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    with _open(req) as r:
        session = r.headers["Location"]

    sent: int | None = 0    # None = 서버에 어디까지 받았는지 물어본다
    fails = 0
    with open(path, "rb") as f:
        while True:
            if is_cancelled():
                raise Cancelled()
            if sent is None:
                chunk, rng = b"", f"bytes */{size}"
            else:
                f.seek(sent)
                chunk = f.read(CHUNK)
                rng = f"bytes {sent}-{sent + len(chunk) - 1}/{size}"
            req = urllib.request.Request(session, chunk, method="PUT", headers={**auth, "Content-Range": rng})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())["id"]
            except urllib.error.HTTPError as e:
                if e.code == 308:   # 아직 남음: Range = "bytes=0-마지막으로 받은 바이트"
                    got = e.headers.get("Range")
                    sent = int(got.rsplit("-", 1)[1]) + 1 if got else 0
                    fails = 0
                    if progress:
                        progress(sent / size)
                    continue
                if e.code < 500 or fails >= RETRIES:
                    raise ApiError(e) from None
            except OSError:
                if fails >= RETRIES:
                    raise RuntimeError("인터넷 연결이 끊겨 업로드하지 못했습니다. 다시 시도하세요.") from None
            fails += 1
            time.sleep(2 ** fails)
            sent = None


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"
