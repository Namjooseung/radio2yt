"""음성/음악/잡음 구간 판별기 — TensorFlow 없이 onnxruntime으로 실행.

inaSpeechSegmenter 0.7.12 (MIT, INA)의 Segmenter(vad_engine='smn', detect_gender=False)
처리 흐름을 그대로 옮겼다. 원본과 같은 입력이면 같은 결과를 낸다.
"""
from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import onnxruntime as ort

from .vendor.pyannote_viterbi import viterbi_decoding
from .vendor.sidekit_mfcc import mfcc
from .vendor.viterbi_utils import diag_trans_exp, log_trans_exp, pred2logemission

OUTLABELS = ("speech", "music", "noise")
NMEL = 21
VITERBI_ARG = 80
ENERGY_RATIO = 0.03
PATCH_W, PATCH_STEP = 68, 2
FRAME_SEC = 0.02


def resource_dir() -> Path:
    """PyInstaller로 묶였을 때와 개발 중일 때 모두 engine 폴더 위치를 돌려준다."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "engine" if base else Path(__file__).parent


def _no_window_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def decode_16k_mono(path: str, ffmpeg: str = "ffmpeg") -> np.ndarray:
    """ffmpeg로 16kHz 모노 PCM16을 받아 float32(-1~1)로 돌려준다 (원본의 임시 wav + soundfile 읽기와 같은 값)."""
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-ar", "16000", "-ac", "1", "-f", "s16le", "-"],
        capture_output=True, creationflags=_no_window_flags(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "ffmpeg 오류")
    return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0


def _binidx2seglist(binidx):
    curlabel, bseg, ret = None, -1, []
    i = -1
    for i, e in enumerate(binidx):
        if e != curlabel:
            if curlabel is not None:
                ret.append((curlabel, bseg, i))
            curlabel, bseg = e, i
    ret.append((curlabel, bseg, i + 1))
    return ret


def _energy_activity(loge, ratio):
    threshold = np.mean(loge[np.isfinite(loge)]) + np.log(ratio)
    raw_activity = loge > threshold
    return viterbi_decoding(pred2logemission(raw_activity), log_trans_exp(150, cost0=-5))


FRAME_LEN, FRAME_HOP = 400, 160      # mfcc 기본값 (25ms 창, 10ms 간격, 16kHz)
FEAT_CHUNK_FRAMES = 20000            # 특징 추출 묶음: 약 3분 20초 분량
PATCH_CHUNK = 1024                   # CNN 입력 묶음


def _features(sig: np.ndarray, progress=None):
    """mfcc(get_mspec=True)를 신호 조각별로 나눠 계산한다 (메모리 절약).

    프레임은 서로 독립(프레임 k = sig[160k:160k+400], 프리엠퍼시스도 프레임 안에서만 적용)이라
    프레임 경계에 맞춰 나누면 한 번에 계산한 것과 같은 값이 나온다.
    """
    n_frames = (len(sig) - FRAME_LEN) // FRAME_HOP + 1
    loges, mspecs = [], []
    for k0 in range(0, max(n_frames, 0), FEAT_CHUNK_FRAMES):
        k1 = min(k0 + FEAT_CHUNK_FRAMES, n_frames)
        sub = sig[k0 * FRAME_HOP: (k1 - 1) * FRAME_HOP + FRAME_LEN]
        _, loge, _, mspec = mfcc(sub, get_mspec=True)
        loges.append(loge)
        mspecs.append(mspec)
        if progress:
            progress(k1 / n_frames)
    if not loges:  # 아주 짧은 파일
        _, loge, _, mspec = mfcc(sig, get_mspec=True)
        return loge, mspec
    return np.concatenate(loges), np.concatenate(mspecs)


class _PatchSource:
    """_get_patches 결과를 한꺼번에 만들지 않고, 필요한 범위만 같은 계산으로 만들어 준다."""

    def __init__(self, mspec, w, step):
        self.w, self.h = w, mspec.shape[1]
        self.windows = np.lib.stride_tricks.sliding_window_view(mspec, (w, self.h))[::step, 0]
        self.nwin = len(self.windows)
        self.lpad = w // (2 * step)
        rpad = w // (2 * step) - 1 + len(mspec) % 2
        self.total = self.lpad + self.nwin + rpad

    def get(self, a: int, b: int):
        idx = np.clip(np.arange(a, b) - self.lpad, 0, self.nwin - 1)
        data = self.windows[idx].reshape(len(idx), self.w * self.h)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            data = (data - data.mean(axis=1, keepdims=True)) / data.std(axis=1, keepdims=True)
        finite = np.all(np.isfinite(data), axis=1)
        return data.reshape(len(idx), self.w, self.h), finite


def _get_patches(mspec, w, step):
    h = mspec.shape[1]
    data = np.lib.stride_tricks.sliding_window_view(mspec, (w, h))[::step, 0]
    data = data.reshape(len(data), w * h)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        data = (data - data.mean(axis=1, keepdims=True)) / data.std(axis=1, keepdims=True)
    lfill = [data[0, :].reshape(1, h * w)] * (w // (2 * step))
    rfill = [data[-1, :].reshape(1, h * w)] * (w // (2 * step) - 1 + len(mspec) % 2)
    data = np.vstack(lfill + [data] + rfill)
    finite = np.all(np.isfinite(data), axis=1)
    return data.reshape(len(data), w, h), finite


class Segmenter:
    def __init__(self, ffmpeg: str = "ffmpeg", model_path: str | None = None, batch_size: int = 1024):
        self.ffmpeg = ffmpeg
        self.batch_size = batch_size
        model_path = model_path or str(resource_dir() / "models" / "speech_music_noise.onnx")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name

    def _predict(self, batch: np.ndarray, progress=None) -> np.ndarray:
        out = []
        n = len(batch)
        for i in range(0, n, self.batch_size):
            chunk = batch[i:i + self.batch_size].astype(np.float32)[..., None]
            out.append(self.sess.run(None, {self.input_name: chunk})[0])
            if progress:
                progress(min(i + self.batch_size, n) / n)
        return np.concatenate(out) if out else np.zeros((0, 3), np.float32)

    def segment_signal(self, sig: np.ndarray, progress=None):
        """progress(stage, fraction) 콜백: stage는 'features' 또는 'analyze'."""
        if progress:
            progress("features", 0.0)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            loge, mspec = _features(sig.astype(np.float32, copy=False),
                                    lambda f: progress and progress("features", f))
        difflen = 0
        if len(loge) < 68:
            difflen = 68 - len(loge)
            mspec = np.concatenate((mspec, np.ones((difflen, 24)) * np.min(mspec)))

        # 1) 에너지 기반 활동 감지
        lseg = []
        for lab, start, stop in _binidx2seglist(_energy_activity(loge, ENERGY_RATIO)[::2]):
            lseg.append(("energy" if lab else "noEnergy", start, stop))

        # 2) 에너지 구간을 CNN으로 speech/music/noise 판별 — 조각을 PATCH_CHUNK개씩 만들어 바로 판별
        src = _PatchSource(mspec[:, :NMEL].copy(), PATCH_W, PATCH_STEP)
        total = src.total - (int(difflen / 2) if difflen > 0 else 0)
        energy = [(s, min(e, total)) for lab, s, e in lseg if lab == "energy"]
        n_all = sum(e - s for s, e in energy) or 1
        preds, done = {}, 0
        for s, e in energy:
            outs, fins = [], []
            for a in range(s, e, PATCH_CHUNK):
                b = min(a + PATCH_CHUNK, e)
                patches, finite = src.get(a, b)
                outs.append(self.sess.run(None, {self.input_name: patches.astype(np.float32)[..., None]})[0])
                fins.append(finite)
                done += b - a
                if progress:
                    progress("analyze", done / n_all)
            preds[s] = (np.concatenate(outs), np.concatenate(fins))

        ret = []
        for lab, start, stop in lseg:
            if lab != "energy":
                ret.append((lab, start, stop))
                continue
            r, fin = preds[start]
            r = r.copy()
            r[~fin, :] = 0.5
            pred = viterbi_decoding(np.log(r), diag_trans_exp(VITERBI_ARG, len(OUTLABELS)))
            for lab2, s2, e2 in _binidx2seglist(pred):
                ret.append((OUTLABELS[int(lab2)], s2 + start, e2 + start))

        return [(lab, s * FRAME_SEC, e * FRAME_SEC) for lab, s, e in ret]

    def __call__(self, path: str, progress=None):
        if progress:
            progress("decode", 0.0)
        sig = decode_16k_mono(path, self.ffmpeg)
        if progress:
            progress("decode", 1.0)
        return self.segment_signal(sig, progress)
