# 제3자 구성 요소

이 저장소에는 다음 외부 구성 요소가 포함되어 있거나, 설치판에 함께 들어갑니다. 각 구성 요소는 원래 라이선스를 따릅니다.

| 구성 요소 | 위치 | 라이선스 | 출처 |
|---|---|---|---|
| inaSpeechSegmenter 음성/음악 판별 모델 (ONNX로 변환) | `engine/models/speech_music_noise.onnx` | MIT | INA (David Doukhan), https://github.com/ina-foss/inaSpeechSegmenter |
| inaSpeechSegmenter 보조 코드 | `engine/vendor/viterbi_utils.py` | MIT | INA |
| pyannote Viterbi | `engine/vendor/pyannote_viterbi.py` | MIT | CNRS (pyannote) |
| SIDEKIT MFCC | `engine/vendor/sidekit_mfcc.py` | **LGPL-3.0** (이 파일만 해당. scipy 의존 한 곳을 수정했고 `[radio2yt 수정]`으로 표시) | Anthony Larcher, Sylvain Meignier |
| Pretendard 글꼴 | `assets/fonts/` | SIL Open Font License 1.1 (`assets/fonts/LICENSE.txt`) | https://github.com/orioncactus/pretendard |
| Lucide 아이콘 | `assets/icons/` | ISC (`assets/icons/LICENSE.txt`) | https://lucide.dev |
| 디자인 시스템 문서 | `design/DESIGN.md` | 문서 안의 출처 표기 참고 | goorm Vapor UI 공개 자료를 정리한 문서 |

설치판에만 들어가는 것 (저장소에는 없음):

| 구성 요소 | 라이선스 | 비고 |
|---|---|---|
| FFmpeg (gyan.dev full build) | GPL-3.0 | 설치판의 `_internal/bin/ffmpeg.exe`, 라이선스는 `FFMPEG_LICENSE.txt` |
| Qt / PySide6 | LGPL-3.0 | |
| ONNX Runtime | MIT | |
| NumPy | BSD-3-Clause | |
| Python | PSF License | |
