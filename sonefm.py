"""설치판(PyInstaller) 진입점.

    SoneFMEditor.exe                     프로그램 실행
    SoneFMEditor.exe --selftest 파일.mp3   화면 없이 엔진 점검 (결과는 사용자 폴더의 selftest.txt)
"""
import sys


def selftest(path: str) -> int:
    import time
    import tempfile
    from pathlib import Path
    from app import store
    out = store.data_dir() / "selftest.txt"
    lines = []
    code = 0
    try:
        from engine import pipeline as P
        lines.append(f"ffmpeg: {P.ffmpeg_path()}")
        lines.append(f"info: {P.probe_info(path)}")
        t = time.time()
        a = P.analyze(path)
        lines.append(f"analyze: {time.time() - t:.1f}s, cuts={[(round(c.start, 1), round(c.end, 1)) for c in a.cuts]}, "
                     f"out={a.out_length:.1f}/{a.total:.1f}")
        with tempfile.TemporaryDirectory() as tmp:
            m4a = Path(tmp) / "r.m4a"
            P.build_result_audio(a, str(m4a))
            mp4 = Path(tmp) / "r.mp4"
            thumb = Path(sys._MEIPASS if hasattr(sys, "_MEIPASS") else ".") / "assets" / "thumbnails" / "기본.png"
            P.render_video(str(m4a), str(thumb), str(mp4), a.out_length)
            lines.append(f"render: {mp4.stat().st_size / 1e6:.1f}MB, info={P.probe_info(str(mp4))}")
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401  재생 모듈 확인
        lines.append("QtMultimedia: ok")
        lines.append("RESULT: OK")
    except Exception as e:  # noqa: BLE001
        import traceback
        lines.append(traceback.format_exc())
        lines.append(f"RESULT: FAIL {e}")
        code = 1
    out.write_text("\n".join(lines), encoding="utf-8")
    return code


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    from app.main import main
    main()
