# Typecast 단어 TTS 비교

한국어 단어 전용 TTS를 비교하고, 문맥 문장에서 대상 단어 구간만 잘라내는 재현용 프로젝트입니다.

## 구성

- `typecast_context_cut_test.py`: Typecast API로 음원을 생성하고 timestamp를 이용해 단어 구간을 MP3로 절단합니다.
- `recut_typecast_word_clips.py`: 이미 저장한 전체 문장 음원과 `manifest.json`만으로 다시 절단합니다. API를 호출하지 않습니다.
- `typecast-sdk-quality-test-jinhee-eunsol-20-words-v2/`: 최종 비교 샘플 20개, 진희·은솔 음원, 원본 문장 음원, 절단 기준이 담긴 매니페스트입니다.
- `dist/`: 외부 공유용 비교 페이지와 재생용 최종 클립입니다.

## 사용 환경

- Python 3.11
- FFmpeg (시스템 PATH에서 `ffmpeg` 명령을 실행할 수 있어야 함)
- Typecast API 키
- `typecast-python==0.5.2`

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

## 외부 비교 페이지

최종 재생 클립을 포함한 페이지는 별도로 배포되어 있습니다.

https://stories-tts-voice-comparison.ulruyv.chatgpt.site/
