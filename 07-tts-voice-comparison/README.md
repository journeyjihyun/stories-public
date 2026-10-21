# Typecast 단어 TTS 비교

한국어 단어 전용 TTS를 비교하고, 문맥 문장에서 대상 단어 구간만 잘라내는 재현용 프로젝트입니다.

## 2026-10-21 업데이트 — 현재 생성·가공 방식

기존 20단어 비교 실험과 스크립트는 아래에 보존했습니다. 새 작업은 `pipeline.py`를 사용합니다.
이번 공개 범위는 재현 코드와 예시 입력입니다. 운영 874개 음원, 내부 시트, 검수 코멘트, API 키는 추가하지 않았습니다.

### 바뀐 파일과 역할

| 파일 | 변경 내용 |
| --- | --- |
| `pipeline.py` | `generate` / `recut` CLI, 표시 단어와 발화 입력 분리, 입력 고정·재개, 수동 시작점 override |
| `generation_core.py` | 실제 배치 생성 로직을 공용화. 진희·속도 0.9·피치 0, 원문·단어 timestamp 보존 |
| `recut_waveform_snap_test.py` | 초기 앞쪽 저음량 탐색 로직 보존. 생성 단계의 기본 절단용 |
| `boundary_core.py` | 실제 사용한 양방향 파형 탐색 함수 분리. 재가공 단계에서 사용 |
| `analyze_tts_pitch.py` | F0 기반 끝 억양 상승 후보 탐지. 디코딩한 Sound 입력도 지원 |
| `words.example.json` | 띄어쓰기 단어와 자모의 명시적 발화 입력 예시 |
| `overrides.example.json` | 청취 승인된 수동 경계 지정 형식 예시 |
| `test_pipeline.py` | 앞/뒤 이동, 불명확 경계 유지, API 없는 재가공 테스트 |
| `requirements.txt`, `.gitignore` | 실행 버전 고정 및 로컬 결과·키·환경 제외 |

### 생성 설정

```text
입력 문장: 다음 단어는. '{spoken_text}'.
model: ssfm-v30
voice_id: tc_6731b2b2478a48710ecc9158 (진희)
language: kor
emotion_preset: normal / emotion_intensity: 0.0
audio_tempo: 0.9 / audio_pitch: 0 / audio_format: mp3
timestamp granularity: word
```

속도와 피치는 API 생성 요청에 적용합니다. 후처리로 속도·피치를 바꾸지 않습니다.
기존 안내 문장과 달리 `단어는` 뒤에 마침표가 있습니다. 단독 단어보다 문맥 생성이
끝 억양에 도움이 되었지만 자연스러운 발음이나 문장 간 무음을 보장하지는 않습니다.

### 실행

Python 3.11과 FFmpeg가 필요합니다. 이 디렉터리에서 실행하세요.

```powershell
python -m pip install -r requirements.txt
# API 키를 복사한 뒤, 세션 환경변수에만 설정합니다. 출력하거나 파일에 저장하지 마세요.
$env:TYPECAST_API_KEY = (Get-Clipboard -Raw).Trim()
try {
  python pipeline.py generate --input words.example.json --output output-generated
} finally {
  Remove-Item Env:TYPECAST_API_KEY
}
# 아래 단계는 API 호출 및 키가 필요하지 않습니다.
python pipeline.py recut --input output-generated --output output-recut
python -m unittest test_pipeline.py
```

생성은 글자 수에 따른 유료 API 호출입니다. 입력 전체 문장과 재시도도 비용에 영향을 줄 수 있습니다.
같은 생성 폴더와 입력으로 재실행하면 저장된 원문·메타데이터를 재사용합니다. 입력이나
설정이 바뀌면 새 폴더를 사용하세요. 재가공 출력 폴더는 반드시 새 경로여야 합니다.
`full/` 원문, `metadata/` API 응답, `clips/` MP3, `manifest.json`을 보존하세요.
결과는 생성 버전에 따라 달라지므로 같은 입력으로 동일 음원이 보장되지는 않습니다.

### 절단: timestamp는 기준점이며 정답이 아님

1. 전체 대상 어절의 timestamp suffix를 입력과 대조합니다. `가스 요금`을 마지막 `요금`만 자르지 않습니다.
2. 끝은 마지막 대상 토큰 종료 + 140ms, 원문 길이 이내로 제한합니다.
3. 재가공은 timestamp 앞 180ms~뒤 220ms를 탐색합니다. 이전 토큰 종료-80ms와 대상 종료-120ms로도 제한합니다.
4. 10ms RMS 창·5ms 간격으로 에너지를 측정하고, 임계값은 95백분위 에너지-32dB를 -48~-38dB 범위에 제한합니다.
5. 20ms 이상 저음량 구간이며 전후 60/100ms 내 신호가 임계값보다 8dB 이상 큰 후보를 찾습니다.
6. 후보가 하나면 저음량 구간 시작 +5ms를 선택합니다. 없거나 여러 개면 기존 절단점을 유지합니다.
7. 이동량·후보·실제 시작점·피치 지표를 manifest에 기록하고 반드시 청취합니다.

**주의:** 단어 내부 자음 폐쇄 구간도 저음량이므로 자동 방식은 첫 음절을 자를 수 있습니다.
실제 `어떠하다`는 자동 뒤쪽 이동 대신 원문 1.111초(timestamp)부터 자른 버전이 승인되었습니다.
이 값은 그 원문 전용이며 새로 생성한 모든 `어떠하다`에 적용하면 안 됩니다.

```powershell
# 본인의 원문을 청취하고 예시의 초 값을 수정한 후에만 실행하세요.
python pipeline.py recut --input output-generated --output output-manual --overrides overrides.example.json
```

자모는 `[가-힣]` 필터에서 빠지므로 생성 대상은 명시적 목록으로 관리합니다.
`ㄱ→기역`, `ㅎ→히읗`, `ㅏ→아`, `ㅛ→요`처럼 `spoken_text`를 구분하세요.
`감다→감따`는 된소리 유도용 입력 예외이며 장음까지 보장하지 않습니다.

### 끝 억양 분석 및 검수

파형 크기와 별개로 Praat F0를 10ms 간격, 80~700Hz 범위에서 추적합니다.
끝 구간의 변화가 +2반음 이상이고 기울기가 +20반음/초 이상이면 청취 후보입니다.
이 기준은 초기 40개 비교 샘플에 맞춘 휴리스틱으로, 정확도 검증된 범용 품질 판정기가 아닙니다.
짧은 발화·무성음·옥타브 추적 오류에 취약하며 미탐지/측정 불가를 정상으로 간주하지 않습니다.
869개 재가공 시 `거짓`, `생식`, `이직`이 후보였고 3개는 측정 불가였습니다.

### 이번 배치 결과와 공개 범위

- 최초 869개 → 시트 자모 누락 4개 보완 + S3에만 있던 `졸업하다` 1개 = 최종 874개.
- 869개 자동 가공: 앞쪽 이동 454 / 뒤쪽 이동 271 / 기존 유지 144. 이후 청취 검수·재생성·수동 예외 적용.
- 로컬 검수 화면은 이상 표시·코멘트 저장/내려받기를 지원했으며, 운영 검수 데이터는 이 저장소에 추가하지 않았습니다.
- 최종 조립은 승인 파일을 복사하고 SHA-256·디코딩·ZIP 무결성을 확인했습니다. **S3/CDN 교체는 수행하지 않았습니다.**
- 아래 기존 공개 비교 페이지는 과거 20개 실험입니다. 이번 874개 최종본으로 갱신한 페이지가 아닙니다.

## 이전 비교 실험 (보존)

## 구성

- `typecast_context_cut_test.py`: Typecast API로 음원을 생성하고 timestamp를 이용해 단어 구간을 MP3로 절단합니다.
- `recut_typecast_word_clips.py`: 이미 저장한 전체 문장 음원과 `manifest.json`만으로 다시 절단합니다. API를 호출하지 않습니다.
- `analyze_tts_pitch.py`: 최종 재생 MP3의 F0(기본주파수) 변화로 끝 억양의 상승 후보를 찾습니다. API를 호출하지 않습니다.
- `typecast-sdk-quality-test-jinhee-eunsol-20-words-v2/`: 최종 비교 샘플 20개, 진희·은솔 음원, 원본 문장 음원, 절단 기준이 담긴 매니페스트입니다.
- `dist/`: 외부 공유용 비교 페이지와 재생용 최종 클립입니다.

## 사용 환경

- Python 3.11
- FFmpeg (시스템 PATH에서 `ffmpeg` 명령을 실행할 수 있어야 함)
- Typecast API 키
- `typecast-python==0.5.2`
- `praat-parselmouth==0.4.7` (Praat 기반 음성 F0 분석)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

API 키는 환경변수로만 전달합니다. `.env` 파일이나 키 값 자체를 저장소에 커밋하지 않습니다.

```powershell
$env:TYPECAST_API_KEY = "발급받은_키"
```

## 생성 방식

단독 단어의 끝 억양을 줄이기 위해 API에는 아래와 같은 문맥 문장을 보냅니다.

```text
다음 단어는 '{단어}'.
```

기본 설정은 다음과 같습니다.

- 모델: `ssfm-v30`
- 언어: `kor`
- 프롬프트: `normal`, 강도 `0.0`
- 기본 보이스: 진희(`tc_6731b2b2478a48710ecc9158`), 은솔(`tc_67db72eb93add6902ea41e5c`)
- 출력: MP3

Timestamp TTS의 단어 단위 구간에서 마지막 N개 토큰을 대상 단어로 취급합니다. N은 입력 표제어의 공백 분리 단어 수입니다. 따라서 `가스 요금`, `일기 예보`처럼 띄어쓰기가 있는 표제어도 전체 구간을 유지합니다. 절단 범위는 대상 첫 토큰 시작부터 마지막 토큰 끝 + 140ms입니다.

## 새 단어 생성

아래 예시는 두 보이스로 `가스 요금`, `일기 예보`를 생성하여 새 결과 폴더에 저장합니다.

```powershell
$env:TYPECAST_TEST_WORDS = "가스 요금,일기 예보"
$env:TYPECAST_VOICE_NAMES = "jinhee,eunsol"
$env:TYPECAST_WORD_LEFT = "'"
$env:TYPECAST_WORD_RIGHT = "'"
$env:TYPECAST_OUTPUT_DIR = "typecast-output-example"
python .\typecast_context_cut_test.py
```

각 결과 폴더에는 다음이 생성됩니다.

- `full/`: 문맥 문장 전체 MP3
- `word-only/`: 실제 서비스에서 재사용할 단어 전용 MP3
- `manifest.json`: 입력 문장, timestamp 구간, 절단 시작·종료 시각

## 저장된 원본 다시 자르기

API 비용 없이 시작·종료 기준만 다시 적용하려면 아래를 실행합니다. 기본 입력은 최종 V2 샘플 폴더이며, 결과는 `word-only-recut/`에 생성됩니다.

```powershell
python .\recut_typecast_word_clips.py
```

다른 원본 결과 폴더를 지정할 수도 있습니다.

```powershell
$env:TYPECAST_RECUT_INPUT_DIR = ".\typecast-output-example"
$env:TYPECAST_RECUT_OUTPUT_DIR = ".\typecast-output-example\word-only-recut"
python .\recut_typecast_word_clips.py
```

## 끝 억양 피치 분석

파형의 높낮이는 음량이므로 억양 판단에 직접 쓰지 않습니다. 대신 Praat 기반
`praat-parselmouth`로 F0(기본주파수)를 10ms 간격으로 추출합니다. 무성 자음,
무음, 잘린 음원 끝의 영향을 줄이기 위해 실제 유성 프레임만 사용하고, 유성 시간의
앞 10%와 뒤 7%를 제외한 뒤 후반 55%를 분석합니다.

후반부 F0는 각 클립의 중앙 F0를 기준으로 반음(semitone)으로 바꿉니다. 아래 두
값을 함께 계산합니다.

- `rise_st`: 후반부 첫 1/3과 마지막 1/3의 중앙값 차이
- `slope_st_per_sec`: 후반부 F0의 시간 대비 선형 기울기

현재 비교 샘플의 **명확한 끝올림 이슈 후보** 기준은 `rise_st >= +2.0` 이면서
`slope_st_per_sec >= +20.0`입니다. 이 값은 보편적인 음성 품질 기준이 아니라,
현재 20개 단어 × 진희·은솔 샘플을 듣고 보정한 QA 선별 기준입니다. 전체 생성 전에는
표본을 더 늘려 기준을 다시 확인해야 합니다.

```powershell
python .\analyze_tts_pitch.py
```

기본값은 `dist/audio/`의 최종 재생 클립 40개를 분석합니다. 현재 검증에서는
`정말 · 진희`만 이슈 후보로 나왔습니다(`rise_st = +2.75`,
`slope_st_per_sec = +31.82`). 나머지 39개는 기준 미만이었습니다.

이 환경에서 40개 분석은 약 25초(클립당 약 0.6초)였으며, Typecast API 호출이나
오디오 생성 시간은 포함하지 않습니다.

## 외부 비교 페이지

최종 재생 클립을 포함한 페이지는 별도로 배포되어 있습니다.

https://stories-tts-voice-comparison.ulruyv.chatgpt.site/
