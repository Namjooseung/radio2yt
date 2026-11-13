inaSpeechSegmenter 0.7.12 에서 복사한 파일들. sidekit_mfcc.py 만 한 곳을 수정했다 (scipy dct → numpy 구현, "[radio2yt 수정]" 표시). 나머지는 원본 그대로.

| 파일 | 라이선스 | 원 저작자 |
|---|---|---|
| sidekit_mfcc.py | LGPL-3.0 | SIDEKIT (Anthony Larcher, Sylvain Meignier) |
| pyannote_viterbi.py | MIT | CNRS (pyannote) |
| viterbi_utils.py | MIT | INA (David Doukhan) |

음성/음악 판별 모델(models/speech_music_noise.onnx)은 inaSpeechSegmenter(MIT, INA)의
keras_speech_music_noise_cnn.hdf5 를 tools/convert_model.py 로 변환한 것이다.
