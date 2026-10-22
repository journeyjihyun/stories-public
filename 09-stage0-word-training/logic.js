// 0단계 단어·표현 훈련 — 데이터와 계산 로직 (브라우저와 Node 양쪽에서 사용)
(function (root) {
  'use strict';

  // 예시 스토리 (프로토타입용 창작 문장). [표기:원형] 형식으로 내용어를 표시한다.
  var STORY_SRC = [
    '민지는 [아침:아침]에 [일어나요:일어나다].',
    '[창문:창문]을 [열어요:열다].',
    '[날씨:날씨]가 [정말:정말] [좋아요:좋다].',
    '민지는 [친구:친구]에게 [전화해요:전화하다].',
    '“[같이:같이] [공원:공원]에 [갈까요:가다]?”',
    '[친구:친구]가 [좋다:좋다]고 [말해요:말하다].',
    '[두:두] [사람:사람]은 [공원:공원]에서 [만나요:만나다].',
    '[공원:공원]에 [사람:사람]이 [많아요:많다].',
    '민지와 [친구:친구]는 [커피:커피]를 [마셔요:마시다].',
    '[그리고:그리고] [같이:같이] [걸어요:걷다].',
    '[아침:아침] [공기:공기]가 [정말:정말] [시원해요:시원하다].',
    '민지는 [오늘:오늘]이 [좋아요:좋다].'
  ];

  var MEANING = {
    '아침': 'morning', '일어나다': 'to get up', '창문': 'window', '열다': 'to open',
    '날씨': 'weather', '정말': 'really', '좋다': 'good', '친구': 'friend',
    '전화하다': 'to call', '같이': 'together', '공원': 'park', '가다': 'to go',
    '말하다': 'to say', '두': 'two', '사람': 'person', '만나다': 'to meet',
    '많다': 'many, a lot', '커피': 'coffee', '마시다': 'to drink', '그리고': 'and',
    '걷다': 'to walk', '공기': 'air', '시원하다': 'cool, fresh', '오늘': 'today'
  };

  // 표현 만들기: 스토리별 고정 목록. 원문에서 2~4어절만 가져오고 완전한 문장은 노출하지 않는다.
  var CHUNKS = [
    { id: 'c1', words: ['친구', '전화하다'], tiles: ['친구에게', '전화해요'], pool: ['전화해요', '커피를', '친구에게'], en: 'call a friend' },
    { id: 'c2', words: ['같이', '공원', '가다'], tiles: ['같이', '공원에', '갈까요?'], pool: ['공원에', '갈까요?', '오늘', '같이'], en: 'Shall we go to the park together?' },
    { id: 'c3', words: ['사람', '많다'], tiles: ['사람이', '많아요'], pool: ['많아요', '친구가', '사람이'], en: 'there are a lot of people' },
    { id: 'c4', words: ['커피', '마시다'], tiles: ['커피를', '마셔요'], pool: ['마셔요', '공원에', '커피를'], en: 'drink coffee' },
    { id: 'c5', words: ['정말', '좋다'], tiles: ['정말', '좋아요'], pool: ['좋아요', '같이', '정말'], en: 'really good' },
    { id: 'c6', words: ['아침', '공기'], tiles: ['아침', '공기가'], pool: ['공기가', '아침', '친구에게'], en: 'the morning air' }
  ];
  var CHUNK_SETS = [['c1', 'c2', 'c3'], ['c4', 'c5', 'c6']];
  var CHUNK_BY_ID = {};
  CHUNKS.forEach(function (c) { CHUNK_BY_ID[c.id] = c; });

  var READ_LINE = 0.85; // 읽기 가능선 (토큰 커버리지)
  var SET_SIZE = 5;     // 단어 세트당 단어 수

  function parseSentence(src) {
    var segs = [], re = /\[([^:\]]+):([^\]]+)\]/g, last = 0, m;
    while ((m = re.exec(src))) {
      if (m.index > last) segs.push({ t: src.slice(last, m.index), w: '' });
      segs.push({ t: m[1], w: m[2] });
      last = re.lastIndex;
    }
    if (last < src.length) segs.push({ t: src.slice(last), w: '' });
    return segs;
  }

  var SENTENCES = STORY_SRC.map(parseSentence);

  // 유니크 단어 목록: 등장 순서(first)와 등장 횟수(c)
  var WORDS = [], IDX = {};
  SENTENCES.forEach(function (segs) {
    segs.forEach(function (g) {
      if (!g.w) return;
      if (IDX[g.w] == null) {
        IDX[g.w] = WORDS.length;
        WORDS.push({ w: g.w, m: MEANING[g.w], c: 0, first: WORDS.length });
      }
      WORDS[IDX[g.w]].c += 1;
    });
  });

  var TOTAL = WORDS.reduce(function (a, x) { return a + x.c; }, 0);
  var NEED = Math.ceil(READ_LINE * TOTAL);

  function tokensOf(known) {
    var t = 0;
    WORDS.forEach(function (x) { if (known[x.w]) t += x.c; });
    return t;
  }

  function coverage(known) {
    return tokensOf(known) / TOTAL;
  }

  // 단어 세트 생성:
  // 1) 모르는 단어만 남긴다
  // 2) 등장 횟수 많은 순 → 등장 순으로 정렬
  // 3) 읽기 가능선(NEED 토큰)에 도달할 때까지만 자른다 → 나머지는 '읽으며 익히기'
  // 4) 5개씩 묶고, 마지막 세트가 2개 이하이면 앞 세트에 합친다
  function buildPlan(known) {
    var tok = tokensOf(known);
    var unknown = WORDS.filter(function (x) { return !known[x.w]; })
      .sort(function (a, b) { return (b.c - a.c) || (a.first - b.first); });
    var learn = [], later = [];
    unknown.forEach(function (x) {
      if (tok < NEED) { learn.push(x.w); tok += x.c; } else { later.push(x.w); }
    });
    var sets = [];
    for (var i = 0; i < learn.length; i += SET_SIZE) sets.push(learn.slice(i, i + SET_SIZE));
    if (sets.length > 1 && sets[sets.length - 1].length <= 2) {
      var tail = sets.pop();
      sets[sets.length - 1] = sets[sets.length - 1].concat(tail);
    }
    var inPlan = {};
    learn.forEach(function (w) { inPlan[w] = true; });
    return { sets: sets, later: later, learnCount: learn.length, inPlan: inPlan };
  }

  function isSetDone(set, learned) {
    return set.every(function (w) { return learned[w]; });
  }

  // 표현 만들기 잠금: 단어 세트가 있는데 하나도 끝내지 않았으면 잠김.
  // 단어 세트가 0개(이미 읽기 가능선 이상)면 처음부터 열림.
  function isChunkLocked(plan, learned) {
    if (!plan || !plan.sets.length) return false;
    return !plan.sets.some(function (set) { return isSetDone(set, learned); });
  }

  var api = {
    STORY_SRC: STORY_SRC, MEANING: MEANING, CHUNKS: CHUNKS, CHUNK_SETS: CHUNK_SETS, CHUNK_BY_ID: CHUNK_BY_ID,
    READ_LINE: READ_LINE, SET_SIZE: SET_SIZE, SENTENCES: SENTENCES, WORDS: WORDS, IDX: IDX,
    TOTAL: TOTAL, NEED: NEED,
    parseSentence: parseSentence, tokensOf: tokensOf, coverage: coverage,
    buildPlan: buildPlan, isSetDone: isSetDone, isChunkLocked: isChunkLocked
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Stage0 = api;
})(typeof window !== 'undefined' ? window : globalThis);
