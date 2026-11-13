# CLAUDE.md — radio2yt 작업 안내

방송국(SoneFM 96.3) **내부 편집용** Windows 프로그램이다. 라디오 송출 mp3에서 긴 음악만 잘라내고 썸네일 정지 화면을 붙여 유튜브용 mp4를 만든다. 판매 목적은 없다. 사용자와는 **한국어**로 대화한다.

- **요구사항·결정 기록: [REQUIREMENTS.md](REQUIREMENTS.md)가 기준 문서다.** 사용자가 "적어둬"라고 하면 이 파일에 추가한다. 진행 상황 체크리스트도 이 파일에서 갱신한다.

## 사용자 선호 (반드시 지킬 것)

- **기본기 우선.** 세세한 기능이나 설정 화면보다 핵심 흐름이 잘 되는 것을 원한다. 고급 설정 화면은 일부러 뺐다. 기준값(최소 음악 20초, 여유 1초, 페이드 0.3초)은 `engine/pipeline.py`에 고정한다.
- **디자인: `design/DESIGN.md`가 최우선이다.** 목업(`design/youtube-editor-design/`)은 **화면 구성(배치)만** 참고한다. 색·글꼴·버튼 모양은 전부 DESIGN.md에서 가져온다. 편집 화면 전용 색도 마찬가지다. 목업의 청록·황갈 색을 썼다가 "촌스럽다"는 지적을 받았다.
  - DESIGN.md에 해당 토큰이 없으면 DESIGN.md 팔레트에서 의미에 맞게 고른다. 현재 쓰는 값: 남는 구간 blue-500, 잘린 구간 gray, 짧은 음악(남김) orange(warning), 재생선 red-500. 모든 토큰은 `app/theme.py`에 있다.
  - 라이트 모드만 만든다. 문구는 존댓말, 버튼은 짧은 동사. 아이콘은 Lucide SVG만 쓰고 "▶" 같은 글자 기호는 쓰지 않는다.
- 멘트(speech)는 BGM이 깔려 있어도 **절대 자르지 않는다**. 자르는 쪽은 보수적으로 판단한다.

## 실행 / 개발

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # numpy, onnxruntime, PySide6
.venv\Scripts\python -m app                               # 화면 (또는 실행.bat)
.venv\Scripts\python radio2yt.py 파일.mp3 --dry-run        # 명령줄, 분석만
```

ffmpeg가 PATH에 있어야 한다. 설치판에는 `_internal/bin/ffmpeg.exe`가 들어간다. ffprobe는 쓰지 않는다.

## 구조

- `engine/segmenter.py`: inaSpeechSegmenter(smn, 성별 판별 없음)의 처리 흐름을 onnxruntime으로 옮긴 것이다. **원본 TensorFlow와 결과가 비트 단위로 같아야 한다.** 메모리를 아끼려고 특징 추출(`FEAT_CHUNK_FRAMES`)과 CNN 입력(`PATCH_CHUNK=1024`)을 나눠 처리한다. 57분 방송 기준 최대 메모리 약 0.87GB, 분석 약 27초다.
- `engine/vendor/`: 원본에서 복사한 파일이다. `sidekit_mfcc.py`는 **LGPL**이고, scipy dct를 numpy로 바꾼 한 곳만 수정했다(`[radio2yt 수정]` 표시). 다른 곳은 고치지 않는다.
- `engine/pipeline.py`: 구간 결정(`decide`), 결과 오디오(AAC), mp4 렌더(ffmpeg, 1fps 정지 화면)를 맡는다.
- `app/`: PySide6 화면. `main.py`(흐름), `views/`(빈 화면·변환 중·결과·작업 기록), `widgets/`(타임라인, 썸네일 선택 창), `workers.py`(작업 스레드), `store.py`(`%APPDATA%\SoneFM 유튜브 편집기`).
- `packaging/`: PyInstaller(`sonefm.spec`)와 Inno Setup(`installer.iss`) 설정. `build.ps1` 하나로 설치 파일까지 만든다.

## 주의점 (실제로 겪은 문제)

- **Qt 스레드:** 작업 스레드(`workers.py`)의 신호는 **람다에 연결하지 않는다.** 람다에 연결하면 작업 스레드에서 실행돼 화면이 멈춘다. `@Slot`이 붙은 QObject 메서드에 `Qt.QueuedConnection`으로 연결한다. 화면을 다루는 수신 메서드에는 `workers.check_main_thread()`를 넣어 둔다.
- **화면 없는 모드(`QT_QPA_PLATFORM=offscreen`) 테스트만으로는 부족하다.** 스레드 버그가 offscreen에서는 우연히 통과했다. 실제 화면 모드로도 확인한다.
- **QMediaPlayer:** 음원을 바꾼 직후의 `setPosition`은 무시된다. 그래서 `_pending_seek`에 담아 두고 불러오기가 끝난 뒤 적용한다.
- **PyInstaller:** QtMultimedia는 QtNetwork가 필요하니 excludes에 넣지 않는다. 빌드는 TensorFlow가 없는 깨끗한 `.venv-build`에서 한다.
- **PowerShell 5.1과 Inno Setup:** 한글이 들어간 `.ps1`/`.iss`는 **UTF-8 BOM**이 있어야 한다.
- **GitHub Releases:** 한글 파일 이름이 지워진다. 설치 파일 이름은 영문(`SoneFM-YoutubeEditor-Setup-<버전>.exe`)으로 하고, 한글은 표시 이름(label)에만 쓴다.
- Python 스크립트로 문서를 고칠 때는 `"\b"`, `"\p"` 같은 경로 이스케이프에 주의한다. 날 문자열을 쓰거나 Edit 도구를 쓴다.

## 검증 방법

- **엔진을 고쳤을 때:** TensorFlow 원본과 대조한다. `pip install -r requirements-dev.txt` 후 `inaSpeechSegmenter.Segmenter(vad_engine="smn", detect_gender=False)` 결과와 `engine.segmenter.Segmenter()` 결과가 `==`로 같아야 한다. 대조용 실제 방송 파일은 저장소에 없으니 사용자에게 받는다.
- **설치판:** `SoneFMEditor.exe --selftest 파일.mp3`로 점검하고, 결과는 `%APPDATA%\SoneFM 유튜브 편집기\selftest.txt`에서 본다. ffmpeg를 PATH에서 빼고 돌려서 넣어 둔 ffmpeg로 동작하는지 확인한다.
- **화면:** 자동 흐름 테스트로 확인한다(열기 → 썸네일 → 분석 → 재생 → 영상 만들기 → 작업 기록, 취소). 테스트할 때는 `APPDATA` 환경 변수를 임시 폴더로 바꿔서 **실제 사용자 데이터를 건드리지 않는다.**

## 배포

1. `app/__init__.py`의 `__version__`을 올린다.
2. `.\packaging\build.ps1`을 실행한다. Inno Setup 6이 필요하다.
3. 커밋하고 push한 뒤 `gh release create v<버전> dist/installer/SoneFM-YoutubeEditor-Setup-<버전>.exe`로 Releases에 올린다.

저장소는 https://github.com/Namjooseung/radio2yt (공개, MIT)이다. 커밋 작성자는 noreply 주소를 쓴다.

## 남은 일

- 56화 21:57~22:21 구간(24초 음악)을 잘라도 되는지: 사용자 확인 대기
- 기본 썸네일: 지금은 임시 1장(`assets/thumbnails/기본.png`, `tools/make_default_thumb.py`로 생성). 실제 썸네일을 받으면 교체한다.
- 여러 회차를 한 번에 처리하는 기능은 화면에 없다(명령줄로는 가능).
- 짧은 음악 안내 글자색(orange-600)이 빨강처럼 보이는지 사용자 확인 대기
