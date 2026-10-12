import argparse, json, re, zipfile, collections, difflib, unicodedata, hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
parser=argparse.ArgumentParser(description="어절 누락·추가·중복 및 하이라이트 존재 여부 기계 검수")
parser.add_argument("input", type=Path, help="Google Sheets에서 내려받은 XLSX 파일")
parser.add_argument("--output-dir", type=Path, default=Path("audit-output"))
parser.add_argument("--source-sheet-url", default="", help="원본 탭 URL (#gid=... 포함); 생략하면 결과 링크는 빈 값")
args=parser.parse_args()
P=args.output_dir
P.mkdir(parents=True, exist_ok=True)
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def save(n,x): (P/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def norm(s): return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))
with zipfile.ZipFile(args.input) as z:
    strings=[]
    for _,e in ET.iterparse(z.open('xl/sharedStrings.xml'),events=['end']):
        if e.tag.endswith('}si'):
            strings.append(''.join(t.text or '' for t in e.iter('{'+NS['m']+'}t')));e.clear()
    xfs=ET.fromstring(z.read('xl/styles.xml')).find('m:cellXfs',NS)
    rows=[]
    for _,e in ET.iterparse(z.open('xl/worksheets/sheet2.xml'),events=['end']):
        if not e.tag.endswith('}row'):continue
        vals=['']*19
        for c in e.findall('m:c',NS):
            col=re.sub(r'\d','',c.get('r')); ci=0
            for char in col:ci=ci*26+ord(char)-64
            if ci>19:continue
            v=c.find('m:v',NS);s=v.text if v is not None else ''
            if c.get('t')=='s':s=strings[int(s)]
            elif c.get('t')=='inlineStr':s=''.join(t.text or '' for t in c.iter('{'+NS['m']+'}t'))
            elif s and c.get('t') in (None,'n'):
                f=float(s);fmt=xfs[int(c.get('s','0'))].get('numFmtId')
                s=f'{f*100:.0f}%' if fmt=='9' else f'{f*100:.2f}%' if fmt=='10' else f'{f:,.0f}' if fmt=='3' else str(int(f)) if f.is_integer() else s
            vals[ci-1]=s
        if any(vals):rows.append({'row':int(e.get('r')),'v':vals})
        e.clear()
assert rows[0]['v'][8:11]==['어절','표제어','하이라이트_텍스트']
data=rows[1:]; groups=collections.defaultdict(list)
for r in data:
    v=r['v'];groups[(v[1],v[2],v[5])].append(r)
issues=[]; excluded=0
def add(kind,rs,expected,current,action,evidence):
    v=rs[0]['v'];loc=','.join(str(r['row']) for r in rs)
    issues.append([kind,expected,current,action,v[6],v[1],v[4],v[5],v[2],loc,','.join(r['v'][0] for r in rs),','.join(r['v'][7] for r in rs),' / '.join(r['v'][8] for r in rs),' / '.join(r['v'][9] for r in rs),' / '.join(r['v'][10] for r in rs),evidence,(args.source_sheet_url+'&range=A'+str(rs[0]['row'])+':S'+str(rs[-1]['row']) if args.source_sheet_url else '')])
def tokens(s):return [norm(x) for x in s.split() if norm(x)]
for rs in groups.values():
    rs.sort(key=lambda r:int(r['v'][7]))
    sentence=rs[0]['v'][6];expected=tokens(sentence);raw_expected=[x for x in sentence.split() if norm(x)]
    actual=[(norm(r['v'][8]),r) for r in rs if norm(r['v'][8])]
    ev=[x for x,r in actual]
    # Ignore punctuation and spacing/boundary-only differences before token alignment.
    if ''.join(expected)!=''.join(ev):
        ambiguous=False
        for op,i,j,k,l in difflib.SequenceMatcher(None,expected,ev,autojunk=False).get_opcodes():
            if op=='equal':continue
            position=f'{i+1}~{j}번째 어절' if i<j else f'{i}번째 어절 뒤'
            context=f'원문 {position}; 앞={expected[i-1] if i else "[문장 시작]"}; 뒤={expected[j] if j<len(expected) else "[문장 끝]"}'
            if op=='delete':
                add('어절 누락',rs,' / '.join(raw_expected[i:j]),'(없음)','원문에서 누락 어절 행을 복구하고 순서를 재부여. 새 행의 표제어·하이라이트는 별도 추출.',context)
            elif op=='insert':
                sub=[r for _,r in actual[k:l]]
                dup=all(ev.count(t)>expected.count(t) and t in expected for t in ev[k:l])
                add('어절 중복' if dup else '어절 추가',sub,'(해당 위치에 어절 없음)',' / '.join(r['v'][8] for r in sub),'원문과 위치 대조 후 불필요한 어절 행을 삭제하고 순서를 재부여.',context)
            elif ''.join(expected[i:j])!=''.join(ev[k:l]):
                # Replacement or partial spelling differences cannot establish whole-token omission/addition.
                ambiguous=True
        if ambiguous:excluded+=1
    for r in rs:
        v=r['v'];e,h=v[8],v[10]
        if not h or h not in e:
            add('하이라이트 비어 있음' if not h else '하이라이트 어절 내 미존재',[r],e,h or '(빈 값)','어절에 실제 존재하는 연속 문자열로 하이라이트 수정. 표제어의 의미에 맞는 범위는 별도 확인.','비어 있지 않음 AND highlight in eojeol; 정규화 없이 원문 문자 그대로 비교')
issues.sort(key=lambda r:(0 if r[0].startswith('어절') else 1,int(r[9].split(',')[0]),r[0]))
headers=['오류 유형','기대값 / 기준 어절','현재 문제값','개발자 조치','원문 문장','콘텐츠_SN','제목','문장_순서','콘텐츠_유형','원본 시트 행 (검수 시점)','원본 # (행 ID)','어절_순서','현재 어절','현재 표제어','현재 하이라이트','판정 근거 / 위치','원본 링크']
report=[headers]+issues
counts=collections.Counter(x[0] for x in issues)
wordkeys={(x[5],x[8],x[7]) for x in issues if x[0].startswith('어절')}
highlight=sum(v for k,v in counts.items() if k.startswith('하이라이트'))
meta={'source_rows':len(data),'sentences':len(groups),'counts':dict(counts),'word_sentences':len(wordkeys),'highlight_rows':highlight,'issue_rows':len(issues),'excluded_replacement_sentences':excluded,'source_sha256':hashlib.sha256((args.input).read_bytes()).hexdigest()}
save('v2_report.json',report);save('v2_meta.json',meta)
for i in range(0,len(report),250):save(f'v2_chunk_{i//250:03}.json',{'start':i,'rows':report[i:i+250]})
print(json.dumps(meta,ensure_ascii=False,indent=2))
print(json.dumps(issues[:8],ensure_ascii=False))
