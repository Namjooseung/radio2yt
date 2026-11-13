"""분석 → 자를 구간 결정 → 미리듣기 오디오 → mp4 생성.

화면(app)과 명령줄(radio2yt.py)이 함께 쓴다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .segmenter import Segmenter, decode_16k_mono, resource_dir

# 고정 기준값 (REQUIREMENTS.md: 설정 화면 없음)
MIN_MUSIC = 20.0      # 이 길이 이상 음악만 자른다
GAP_MERGE = 2.0       # 음악 사이 이 길이 이하 무음/잡음은 합친다
MARGIN = 1.0          # 말 보호용 여유
FADE = 0.3            # 이음새 페이드
SHORT_SHOW = 10.0     # 이 길이 이상 20초 미만 음악은 "짧은 음악(남김)"으로 표시
PEAK_BINS = 3000      # 파형 막대 데이터 개수
VIDEO_W, VIDEO_H = 1920, 1080
AUDIO_BITRATE = "192k"


class Cancelled(Exception):
    pass


def ffmpeg_path(name: str = "ffmpeg") -> str:
    """설치판에 들어 있는 ffmpeg를 먼저 찾고, 없으면 PATH에서 찾는다."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    for cand in (resource_dir().parent / "bin" / exe, Path(sys.executable).parent / "bin" / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name}을(를) 찾을 수 없습니다.")
    return found


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class Span:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class Analysis:
    source: str
    total: float
    segments: list            # [(label, start, end)] 원본 분석 결과
    cuts: list[Span]          # 실제로 잘라내는 구간
    short_music: list[Span]   # 20초 미만이라 남긴 음악 (표시용)
    keeps: list[Span]         # 남는 구간
    peaks: np.ndarray = field(repr=False)  # 0~1 파형 크기, PEAK_BINS개

    @property
    def out_length(self) -> float:
        return sum(k.length for k in self.keeps)

    @property
    def cut_length(self) -> float:
        return self.total - self.out_length

    def result_to_orig(self, t: float) -> float:
        """결과 오디오 시각 → 원본 시각."""
        acc = 0.0
        for k in self.keeps:
            if t <= acc + k.length:
                return k.start + (t - acc)
            acc += k.length
        return self.total

    def orig_to_result(self, t: float) -> float:
        """원본 시각 → 결과 오디오 시각 (잘린 구간 안이면 그 다음 남는 구간의 시작)."""
        acc = 0.0
        for k in self.keeps:
            if t < k.start:
                return acc
            if t <= k.end:
                return acc + (t - k.start)
            acc += k.length
        return acc


# ── 구간 결정 ──────────────────────────────────────────────

GAP_LABELS = {"noise", "noEnergy"}


def find_music_blocks(segments, gap_merge: float = GAP_MERGE) -> list[Span]:
    """music 구간을 짧은 noise/noEnergy 틈을 사이에 두고 합친다. speech가 나오면 끊는다."""
    blocks, cur, in_gap = [], None, False
    for label, start, end in segments:
        if label == "music":
            if cur is not None and (not in_gap or start - cur[1] <= gap_merge):
                cur[1] = end
            else:
                if cur is not None:
                    blocks.append(Span(*cur))
                cur = [start, end]
            in_gap = False
        elif label in GAP_LABELS and cur is not None:
            in_gap = True
            if end - cur[1] > gap_merge:
                blocks.append(Span(*cur))
                cur, in_gap = None, False
        else:
            if cur is not None:
                blocks.append(Span(*cur))
            cur, in_gap = None, False
    if cur is not None:
        blocks.append(Span(*cur))
    return blocks


def decide(segments, total: float, min_music=MIN_MUSIC, gap_merge=GAP_MERGE, margin=MARGIN):
    cuts, short = [], []
    for b in find_music_blocks(segments, gap_merge):
        if b.length < min_music:
            if b.length >= SHORT_SHOW:
                short.append(b)
            continue
        s = 0.0 if b.start <= 0.05 else b.start + margin
        e = total if b.end >= total - 0.05 else b.end - margin
        if e - s > 0.5:
            cuts.append(Span(s, e))
    keeps, pos = [], 0.0
    for c in cuts:
        if c.start > pos:
            keeps.append(Span(pos, c.start))
        pos = max(pos, c.end)
    if pos < total:
        keeps.append(Span(pos, total))
    keeps = [k for k in keeps if k.length > 0.05]
    return cuts, short, keeps


def compute_peaks(sig: np.ndarray, bins: int = PEAK_BINS) -> np.ndarray:
    if len(sig) == 0:
        return np.zeros(bins, np.float32)
    n = len(sig) // bins * bins
    if n == 0:
        return np.zeros(bins, np.float32)
    rms = np.sqrt(np.mean(sig[:n].reshape(bins, -1) ** 2, axis=1))
    ref = np.percentile(rms, 99) or 1.0
    return np.clip(rms / ref, 0, 1).astype(np.float32)


# ── 실행 단계 ──────────────────────────────────────────────

_segmenter: Segmenter | None = None


def get_segmenter() -> Segmenter:
    global _segmenter
    if _segmenter is None:
        _segmenter = Segmenter(ffmpeg=ffmpeg_path())
    return _segmenter


def analyze(path: str, progress=None, is_cancelled=lambda: False) -> Analysis:
    """progress(stage, fraction): stage는 'decode' → 'analyze' → 'refine'."""
    def report(stage, f):
        if is_cancelled():
            raise Cancelled()
        if progress:
            progress(stage, f)

    report("decode", 0.0)
    sig = decode_16k_mono(path, ffmpeg_path())
    total = len(sig) / 16000.0
    report("decode", 1.0)

    seg = get_segmenter()

    def seg_progress(stage, f):
        # features(멜 스펙트럼)는 분석의 앞 15%, analyze(CNN)는 나머지
        report("analyze", 0.15 * f if stage == "features" else 0.15 + 0.85 * f)

    segments = seg.segment_signal(sig, seg_progress)
    report("refine", 0.0)
    cuts, short, keeps = decide(segments, total)
    peaks = compute_peaks(sig)
    report("refine", 1.0)
    return Analysis(path, total, segments, cuts, short, keeps, peaks)


def _audio_filter(keeps: list[Span], total: float, src_label: str = "0:a") -> str:
    parts, labels = [], []
    for i, k in enumerate(keeps):
        f = min(FADE, k.length / 2)
        chain = f"[{src_label}]atrim=start={k.start:.3f}:end={k.end:.3f},asetpts=PTS-STARTPTS"
        if k.start > 0.05:
            chain += f",afade=t=in:d={f:.3f}"
        if k.end < total - 0.05:
            chain += f",afade=t=out:st={k.length - f:.3f}:d={f:.3f}"
        parts.append(chain + f"[a{i}]")
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"concat=n={len(keeps)}:v=0:a=1[aout]")
    return ";".join(parts)


def _run_ffmpeg(args: list[str], duration: float, progress=None, is_cancelled=lambda: False):
    """ffmpeg 실행. -progress 출력으로 진행률(0~1)을 알린다. 취소되면 프로세스를 끝낸다."""
    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1"] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", creationflags=_no_window())
    try:
        for line in proc.stdout:
            if is_cancelled():
                proc.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") and progress and duration > 0:
                try:
                    progress(min(int(line.split("=")[1]) / 1e6 / duration, 1.0))
                except ValueError:
                    pass
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.read().strip() or "ffmpeg 오류")
    finally:
        if proc.poll() is None:
            proc.kill()
    if progress:
        progress(1.0)


def build_result_audio(a: Analysis, out_path: str, progress=None, is_cancelled=lambda: False):
    """남는 구간을 이어 붙인 결과 오디오(AAC)를 만든다. 미리듣기와 영상에 함께 쓴다."""
    if not a.keeps:
        raise RuntimeError("남는 구간이 없습니다.")
    args = ["-i", a.source, "-filter_complex", _audio_filter(a.keeps, a.total),
            "-map", "[aout]", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000",
            "-ac", "2", str(out_path)]
    _run_ffmpeg(args, a.out_length, progress, is_cancelled)


def render_video(result_audio: str, thumb: str, out_mp4: str, duration: float,
                 progress=None, is_cancelled=lambda: False):
    """결과 오디오 + 썸네일 정지 화면 → mp4 (1920x1080, h264/aac)."""
    vf = (f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
          f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p,fps=1")
    Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)
    args = ["-loop", "1", "-framerate", "1", "-i", str(thumb), "-i", str(result_audio),
            "-vf", vf, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium", "-crf", "23",
            "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out_mp4)]
    _run_ffmpeg(args, duration, progress, is_cancelled)


def probe_info(path: str) -> dict:
    """길이(초), 비트레이트(kbps), 파일 크기(MB)."""
    # ffprobe 없이 ffmpeg 하나로 처리한다 (설치판에 ffmpeg만 넣기 위해)
    err = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_no_window(),
    ).stderr
    import re
    duration = kbps = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"bitrate:\s*(\d+)\s*kb/s", err)
    if m:
        kbps = float(m[1])
    return {"duration": duration, "kbps": kbps, "mb": Path(path).stat().st_size / 1e6}
