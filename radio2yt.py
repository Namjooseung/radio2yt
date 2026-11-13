"""라디오 방송 mp3 → 유튜브용 mp4 (명령줄 버전).

    python radio2yt.py input/                      # 폴더 안의 오디오 전부 (같은 이름의 이미지를 썸네일로)
    python radio2yt.py ep01.mp3 --thumb ep01.jpg   # 파일 하나
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from engine import pipeline as P

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]


def fmt(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600):d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def find_thumb(audio: Path) -> Path | None:
    for ext in IMAGE_EXTS:
        if audio.with_suffix(ext).exists():
            return audio.with_suffix(ext)
    images = [p for p in audio.parent.iterdir() if p.suffix.lower() in IMAGE_EXTS]
    return images[0] if len(images) == 1 else None


def process(audio: Path, thumb: Path | None, out_dir: Path, dry_run: bool) -> bool:
    print(f"\n=== {audio.name} ===", flush=True)
    thumb = thumb or find_thumb(audio)
    if thumb is None and not dry_run:
        print(f"  [건너뜀] 썸네일 없음 ({audio.stem}.jpg/.png 를 같은 폴더에 두세요)")
        return False

    print("  분석 중...", flush=True)
    a = P.analyze(str(audio))
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"원본: {audio.name}  ({fmt(a.total)})", f"썸네일: {thumb.name if thumb else '-'}",
             f"잘라낸 음악 구간 {len(a.cuts)}개:"]
    lines += [f"  {fmt(c.start)} ~ {fmt(c.end)}  ({c.length:5.1f}초)" for c in a.cuts]
    if a.short_music:
        lines.append(f"남긴 짧은 음악 {len(a.short_music)}개:")
        lines += [f"  {fmt(s.start)} ~ {fmt(s.end)}  ({s.length:5.1f}초)" for s in a.short_music]
    lines.append(f"최종 길이: {fmt(a.out_length)}  (잘라낸 시간 {fmt(a.cut_length)})")
    print("\n".join("  " + l for l in lines[2:]), flush=True)
    detail = ["", "[원본 분석 구간]"] + [f"  {fmt(s)} ~ {fmt(e)}  {l}" for l, s, e in a.segments]
    (out_dir / f"{audio.stem}_cuts.txt").write_text("\n".join(lines + detail), encoding="utf-8")

    if dry_run:
        return True
    out = out_dir / f"{audio.stem}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        m4a = Path(tmp) / "result.m4a"
        print("  결과 오디오 만드는 중...", flush=True)
        P.build_result_audio(a, str(m4a))
        print(f"  mp4 만드는 중 → {out}", flush=True)
        P.render_video(str(m4a), str(thumb), str(out), a.out_length)
    print("  완료", flush=True)
    return True


def main():
    p = argparse.ArgumentParser(description="라디오 mp3에서 긴 음악을 잘라내고 썸네일 mp4로 변환")
    p.add_argument("input", help="오디오 파일 또는 폴더")
    p.add_argument("--thumb", help="썸네일 이미지 (파일 하나 처리 시)")
    p.add_argument("-o", "--output", default="output", help="결과 폴더 (기본: output)")
    p.add_argument("--dry-run", action="store_true", help="분석만 하고 mp4는 만들지 않음")
    args = p.parse_args()

    src = Path(args.input)
    if src.is_dir():
        jobs = [(f, None) for f in sorted(src.iterdir()) if f.suffix.lower() in AUDIO_EXTS]
    elif src.is_file():
        jobs = [(src, Path(args.thumb) if args.thumb else None)]
    else:
        sys.exit(f"입력을 찾을 수 없습니다: {src}")
    if not jobs:
        sys.exit(f"{src} 에 오디오 파일이 없습니다.")

    ok = sum(process(a, t, Path(args.output), args.dry_run) for a, t in jobs)
    print(f"\n{ok}/{len(jobs)}개 처리 완료.")


if __name__ == "__main__":
    main()
