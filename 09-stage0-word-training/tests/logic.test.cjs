// 실행: node --test tests/logic.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../logic.js');

function knownOf(list) {
  const k = {};
  list.forEach((w) => { k[w] = true; });
  return k;
}

const BEGINNER = ['커피', '친구', '좋다', '사람', '가다', '오늘', '정말', '그리고'];

test('토큰 합계와 읽기 가능선', () => {
  assert.equal(S.WORDS.length, 24);
  assert.equal(S.TOTAL, 34);
  assert.equal(S.NEED, 29);
});

test('아는 단어는 단어 세트에서 빠지고, 85%선까지만 세트가 만들어진다', () => {
  const known = knownOf(BEGINNER);
  const plan = S.buildPlan(known);
  const all = plan.sets.flat();
  BEGINNER.forEach((w) => assert.ok(!all.includes(w), w + '가 세트에 포함됨'));
  assert.equal(plan.learnCount, 11);
  assert.deepEqual(plan.sets.map((s) => s.length), [5, 6]);
  assert.equal(plan.later.length, 5);
  assert.deepEqual(plan.sets[0].slice(0, 3), ['공원', '아침', '같이']);

  const after = Object.assign({}, known);
  all.forEach((w) => { after[w] = true; });
  assert.ok(S.tokensOf(after) >= S.NEED);
});

test('마지막 세트가 2개 이하면 앞 세트에 합친다', () => {
  const plan = S.buildPlan(knownOf(['커피', '친구', '좋다']));
  plan.sets.forEach((s) => assert.ok(s.length >= 3));
});

test('이미 읽기 가능선 이상이면 단어 세트가 없고 표현 만들기가 열려 있다', () => {
  const known = knownOf(S.WORDS.map((x) => x.w).filter((w) => !['공기', '시원하다', '창문'].includes(w)));
  assert.ok(S.coverage(known) >= S.READ_LINE);
  const plan = S.buildPlan(known);
  assert.equal(plan.sets.length, 0);
  assert.equal(S.isChunkLocked(plan, {}), false);
});

test('표현 만들기는 단어 세트를 1개 끝내면 열린다', () => {
  const plan = S.buildPlan(knownOf(BEGINNER));
  assert.equal(S.isChunkLocked(plan, {}), true);
  const learned = {};
  plan.sets[1].forEach((w) => { learned[w] = true; });
  assert.equal(S.isChunkLocked(plan, learned), false);
});

test('표현 만들기는 고정 6개, 3개씩 2세트', () => {
  assert.equal(S.CHUNKS.length, 6);
  assert.deepEqual(S.CHUNK_SETS.map((s) => s.length), [3, 3]);
  S.CHUNKS.forEach((c) => c.tiles.forEach((t) => assert.ok(c.pool.includes(t))));
});
