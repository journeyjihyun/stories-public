# Typecast 단어 음원 생성 → 가공

진희 목소리로 문장을 생성한 뒤, 필요한 단어 부분만 잘라 MP3로 저장합니다.
현재 코드는 `generate.py`, `process.py` 두 파일입니다. 이전 코드·샘플·상세 기록은 [legacy](legacy/README.md)에 보존했습니다.

## 준비

Python 3.11, FFmpeg가 필요합니다. `ffmpeg`가 PATH에 등록된 상태에서 이 폴더에서 실행하세요.

```powershell
python -m pip install -r requirements.txt
```

`words.example.json`에 생성할 단어를 넣습니다. `word`는 표시 단어이며, 발화가 다르면 `spoken_text`를 지정합니다.

```json
{"items": [{"word": "가스 요금"}, {"word": "ㄱ", "spoken_text": "기역"}]}
```

## 1. 생성

설정: 진희(`tc_6731b2b2478a48710ecc9158`), `ssfm-v30`, 한국어, normal·강도 0, **속도 0.9·피치 0**, MP3.
입력 문장은 **다음 단어는. '{단어}'.** 입니다. 속도와 피치는 생성 API에 적용합니다.

API 키를 복사한 뒤 실행합니다. 키는 파일에 저장하거나 Git에 올리지 마세요.

```powershell
$env:TYPECAST_API_KEY = (Get-Clipboard -Raw).Trim()
try {
  python generate.py --input words.example.json --output output-generated
} finally {
  Remove-Item Env:TYPECAST_API_KEY
}
```

유료 API 호출입니다. 원문과 단어별 timestamp를 저장하고 초기 절단본도 만듭니다.
같은 입력·폴더로 재실행하면 저장된 원문을 재사용합니다. 입력이나 설정을 바꾸면 새 폴더를 사용하세요.

## 2. 가공

```powershell
python process.py --input output-generated --output output-processed
```

API 호출 없이 원문에서 다시 자릅니다. 띄어쓰기가 있는 단어도 전체 구간을 사용하며,
timestamp 앞 180ms~뒤 220ms 부근의 저음량 구간을 찾습니다. 후보가 하나면 경계를 조정하고, 없거나 여러 개면 초기 절단점을 유지합니다.

- 결과 음원: `output-processed/clips/*.mp3`
- 단어와 파일 대응·절단 위치·피치 상승 후보: `output-processed/manifest.json`
- 재가공용 원문과 timestamp: `output-generated/full/`, `metadata/`, `manifest.json` — 삭제하지 마세요.

자동 절단은 첫소리를 자르거나 앞 문장 소리를 남길 수 있어 **청취 검수가 필요합니다**.
피치 상승 표시는 검수 후보일 뿐이며, 미표시·측정 불가가 정상 판정은 아닙니다.

시작점을 직접 고치려면 `overrides.example.json`의 단어와 `start_seconds`를 **해당 원문 기준 초 단위**로 수정합니다.
예시 값은 다른 음원에 그대로 적용하지 마세요.

```powershell
python process.py --input output-generated --output output-manual --overrides overrides.example.json
```

가공 출력은 항상 새 폴더를 지정합니다. S3/CDN 업로드는 수행하지 않습니다.

## 3. 검수

가공 시 함께 생성된 `output-processed/index.html`을 브라우저에서 엽니다.
처음부터 연속 재생하거나 단어별로 듣고, 이상 표시와 코멘트를 남길 수 있습니다.
재생 오류가 나면 연속 재생을 멈춥니다. `index.html`과 `clips/`는 함께 유지하세요.

검수 기록은 브라우저에 자동 저장되며 원본 manifest를 수정하지 않습니다.
로컬 파일의 저장 지원은 브라우저마다 다르고, 파일 이동·브라우저 변경·데이터 삭제 시 기록이 사라질 수 있습니다.
**검수 결과 내려받기**로 이상 표시·코멘트가 포함된 JSON을 보관하세요.

테스트(API 호출 없음): `python -m unittest discover -s tests`
