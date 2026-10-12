#!/usr/bin/env python3
"""Mechanically audit tokenized sentence rows in a Google Sheets XLSX export."""

import argparse
import collections
import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
MAIN = "{" + NS["m"] + "}"
REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_number(cell_ref):
    letters = re.sub(r"\d", "", cell_ref)
    value = 0
    for char in letters:
        value = value * 26 + ord(char.upper()) - 64
    return value - 1


def load_shared_strings(book):
    try:
        root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.text or "" for node in item.iter(MAIN + "t")) for item in root.findall("m:si", NS)]


def sheet_paths(book):
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target") for rel in rels.findall("{" + REL_PKG + "}Relationship")}
    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        target = targets[sheet.get("{" + REL_DOC + "}id")]
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheets.append((sheet.get("name", ""), path))
    return sheets


def cell_text(cell, strings):
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(MAIN + "t"))
    value = cell.find("m:v", NS)
    raw = value.text if value is not None and value.text is not None else ""
    if kind == "s" and raw:
        return strings[int(raw)]
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def iter_rows(book, path, strings):
    with book.open(path) as stream:
        for _, row in ET.iterparse(stream, events=("end",)):
            if row.tag != MAIN + "row":
                continue
            values = {}
            for cell in row.findall("m:c", NS):
                values[col_number(cell.get("r", "A1"))] = cell_text(cell, strings)
            yield int(row.get("r", "0")), values
            row.clear()


def norm(value):
    return "".join(ch for ch in value if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def punctuation_only(value):
    return bool(value) and not any(ch.isalnum() or unicodedata.category(ch).startswith(("L", "N")) for ch in value)


def numeric_zero_padding_equivalent(expected, actual):
    """Ignore leading-zero loss when a numeric-looking cell was coerced by Sheets."""
    if not re.fullmatch(r"\d+", expected) or not re.fullmatch(r"\d+", actual):
        return False
    return str(int(expected)) == str(int(actual))


def row_link(base_url, row_number):
    if not base_url:
        return ""
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}range=A{row_number}:T{row_number}"


def main():
    parser = argparse.ArgumentParser(description="최신 어절 토큰 시트의 기계적 형식 검수")
    parser.add_argument("input", type=Path, help="Google Sheets에서 다운로드한 XLSX 파일")
    parser.add_argument("--sheet-name", help="검수할 탭 이름(생략 시 review2 탭을 우선 선택)")
    parser.add_argument("--output-dir", type=Path, default=Path("audit-output"))
    parser.add_argument("--source-sheet-url", default="", help="원본 탭 URL (range 링크 생성용)")
    args = parser.parse_args()

    required = ["콘텐츠_SN", "콘텐츠_유형", "문장_순서", "문장", "어절_순서", "어절", "하이라이트_텍스트"]
    events = []
    excluded_replacements = []
    ignored_punctuation_rows = 0
    ignored_numeric_coercions = []
    sentence_groups = collections.defaultdict(list)

    with zipfile.ZipFile(args.input) as book:
        strings = load_shared_strings(book)
        sheets = sheet_paths(book)
        if args.sheet_name:
            candidates = [entry for entry in sheets if entry[0] == args.sheet_name]
        else:
            candidates = [entry for entry in sheets if "review2" in entry[0].lower()]
            if not candidates:
                candidates = [entry for entry in sheets if entry[0] == sheets[0][0]]
        if len(candidates) != 1:
            available = ", ".join(name for name, _ in sheets)
            raise SystemExit(f"검수 탭을 하나로 특정할 수 없습니다. --sheet-name을 지정하세요. 탭: {available}")

        sheet_name, xml_path = candidates[0]
        rows = iter_rows(book, xml_path, strings)
        try:
            header_row, header_cells = next(rows)
        except StopIteration:
            raise SystemExit("선택한 탭이 비어 있습니다.")
        headers = {value.strip(): index for index, value in header_cells.items() if value.strip()}
        missing = [field for field in required if field not in headers]
        if missing:
            raise SystemExit(f"필수 열을 찾지 못했습니다: {', '.join(missing)}")
        def get(values, field):
            return values.get(headers[field], "").strip()

        row_count = 0
        for row_number, values in rows:
            if not any(values.values()):
                continue
            row_count += 1
            data = {name: get(values, name) for name in headers}
            eojeol = data["어절"]
            is_unused_punctuation = punctuation_only(eojeol)
            if not is_unused_punctuation and eojeol and any(ch.isspace() for ch in eojeol.strip()):
                events.append({
                    "오류 유형": "어절 내부 공백",
                    "시트 행": row_number,
                    "문장_토큰_ID": data.get("문장_토큰_ID", ""),
                    "콘텐츠_SN": data["콘텐츠_SN"],
                    "문장": data["문장"],
                    "어절_순서": data["어절_순서"],
                    "현재 어절": eojeol,
                    "원본 링크": row_link(args.source_sheet_url, row_number),
                })

            highlight = data["하이라이트_텍스트"]
            if is_unused_punctuation:
                pass
            elif not highlight:
                events.append({
                    "오류 유형": "하이라이트 비어 있음",
                    "시트 행": row_number,
                    "문장_토큰_ID": data.get("문장_토큰_ID", ""),
                    "콘텐츠_SN": data["콘텐츠_SN"],
                    "문장": data["문장"],
                    "어절_순서": data["어절_순서"],
                    "현재 어절": eojeol,
                    "현재 하이라이트": "",
                    "원본 링크": row_link(args.source_sheet_url, row_number),
                })
            elif highlight not in eojeol:
                events.append({
                    "오류 유형": "하이라이트 어절 내 미존재",
                    "시트 행": row_number,
                    "문장_토큰_ID": data.get("문장_토큰_ID", ""),
                    "콘텐츠_SN": data["콘텐츠_SN"],
                    "문장": data["문장"],
                    "어절_순서": data["어절_순서"],
                    "현재 어절": eojeol,
                    "현재 하이라이트": highlight,
                    "원본 링크": row_link(args.source_sheet_url, row_number),
                })

            sentence_groups[(data["콘텐츠_SN"], data["콘텐츠_유형"], data["문장_순서"])].append((row_number, data))

    for key, group in sentence_groups.items():
        group.sort(key=lambda item: (int(float(item[1]["어절_순서"])) if re.fullmatch(r"-?\d+(?:\.\d+)?", item[1]["어절_순서"]) else 10**12, item[0]))
        sentence = group[0][1]["문장"]
        expected_raw = [token for token in sentence.split() if norm(token)]
        expected = [norm(token) for token in expected_raw]
        token_rows = []
        for row_number, data in group:
            token = data["어절"]
            if punctuation_only(token):
                ignored_punctuation_rows += 1
                continue
            normalized = norm(token)
            if normalized:
                token_rows.append((row_number, data, normalized))
        actual = [item[2] for item in token_rows]

        if collections.Counter(expected) == collections.Counter(actual):
            if expected != actual:
                events.append({
                    "오류 유형": "어절 순서 오류",
                    "콘텐츠_SN": key[0],
                    "콘텐츠_유형": key[1],
                    "문장_순서": key[2],
                    "문장": sentence,
                    "기대 어절 순서": expected_raw,
                    "현재 어절 순서": [item[1]["어절"] for item in token_rows],
                    "시트 행": [item[0] for item in token_rows],
                    "문장_토큰_ID": [item[1].get("문장_토큰_ID", "") for item in token_rows],
                    "원본 링크": row_link(args.source_sheet_url, token_rows[0][0]) if token_rows else "",
                })
            continue

        # Detect leading-zero loss caused by numeric coercion; these are not token errors.
        remaining_actual = list(actual)
        remaining_expected = []
        for expected_token in expected:
            match_index = next((i for i, item in enumerate(remaining_actual) if item == expected_token), None)
            if match_index is not None:
                remaining_actual.pop(match_index)
            else:
                remaining_expected.append(expected_token)
        numeric_pairs = []
        still_expected = []
        for expected_token in remaining_expected:
            match_index = next((i for i, item in enumerate(remaining_actual) if numeric_zero_padding_equivalent(expected_token, item)), None)
            if match_index is None:
                still_expected.append(expected_token)
            else:
                actual_token = remaining_actual.pop(match_index)
                numeric_pairs.append((expected_token, actual_token))
        if numeric_pairs and not still_expected and not remaining_actual:
            ignored_numeric_coercions.append({"문장": sentence, "콘텐츠_SN": key[0], "변환 쌍": numeric_pairs})
            continue

        expected_counts = collections.Counter(expected)
        actual_counts = collections.Counter(actual)
        missing = list((expected_counts - actual_counts).elements())
        surplus = actual_counts - expected_counts
        duplicates = [token for token, count in surplus.items() if expected_counts[token] > 0 for _ in range(count)]
        extra = [token for token, count in surplus.items() if expected_counts[token] == 0 for _ in range(count)]
        if missing:
            events.append({
                "오류 유형": "어절 누락",
                "콘텐츠_SN": key[0], "콘텐츠_유형": key[1], "문장_순서": key[2],
                "문장": sentence, "누락 어절": missing,
                "시트 행": [item[0] for item in group],
                "원본 링크": row_link(args.source_sheet_url, group[0][0]),
            })
        if duplicates:
            events.append({
                "오류 유형": "어절 중복",
                "콘텐츠_SN": key[0], "콘텐츠_유형": key[1], "문장_순서": key[2],
                "문장": sentence, "중복 어절": duplicates,
                "시트 행": [item[0] for item in token_rows],
                "문장_토큰_ID": [item[1].get("문장_토큰_ID", "") for item in token_rows],
                "원본 링크": row_link(args.source_sheet_url, token_rows[0][0]) if token_rows else "",
            })
        if extra:
            events.append({
                "오류 유형": "어절 추가",
                "콘텐츠_SN": key[0], "콘텐츠_유형": key[1], "문장_순서": key[2],
                "문장": sentence, "추가 어절": extra,
                "시트 행": [item[0] for item in token_rows],
                "문장_토큰_ID": [item[1].get("문장_토큰_ID", "") for item in token_rows],
                "원본 링크": row_link(args.source_sheet_url, token_rows[0][0]) if token_rows else "",
            })
        replacements = extra + duplicates
        if missing and replacements:
            excluded_replacements.append({"콘텐츠_SN": key[0], "문장": sentence, "누락 후보": missing, "초과 후보": replacements})

    args.output_dir.mkdir(parents=True, exist_ok=True)
    counts = collections.Counter(event["오류 유형"] for event in events)
    meta = {
        "input_file": args.input.name,
        "sheet_name": sheet_name,
        "source_rows": row_count,
        "sentence_groups": len(sentence_groups),
        "issue_count": len(events),
        "counts": dict(counts),
        "excluded_replacement_sentences": excluded_replacements,
        "ignored_punctuation_only_rows": ignored_punctuation_rows,
        "ignored_numeric_zero_padding_coercions": ignored_numeric_coercions,
        "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
    }
    (args.output_dir / "audit_latest_report.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "audit_latest_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
