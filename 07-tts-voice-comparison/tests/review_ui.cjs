// Dependency-free UI logic test; does not replace real browser/audio QA.
const vm = require('node:vm');
const assert = require('node:assert/strict');
let html='';
process.stdin.setEncoding('utf8');
process.stdin.on('data', part=>html+=part);
process.stdin.on('end', async()=>{
  const payload=JSON.parse(html.match(/type="application\/json">([\s\S]*?)<\/script>/)[1]);
  payload.rows=[{id:'1',word:'첫째',clip:'clips/1.mp3'},{id:'2',word:'둘째',clip:'clips/2.mp3'}];
  function element(){return {children:[],textContent:'',value:'',checked:false,append(...v){this.children.push(...v);},setAttribute(){},classList:{toggle(){}},pause(){},play:async()=>{},click(){this.clicked=true;}};}
  const ids=Object.fromEntries(['data','player','status','list','start','stop','export'].map(k=>[k,element()]));
  ids.data.textContent=JSON.stringify(payload);
  const stored={},blobs=[];
  const context=vm.createContext({document:{getElementById:k=>ids[k],createElement:element},localStorage:{getItem:k=>stored[k],setItem:(k,v)=>stored[k]=v},Blob,URL:{createObjectURL:b=>{blobs.push(b);return 'blob:test';},revokeObjectURL(){}},setTimeout:fn=>fn()});
  vm.runInContext(html.match(/<script>\s*([\s\S]*?)<\/script>/)[1], context);
  assert.equal(ids.list.children.length,2);
  ids.start.onclick(); await Promise.resolve();
  assert.equal(ids.player.src,'clips/1.mp3');
  ids.player.onended(); await Promise.resolve();
  assert.equal(ids.player.src,'clips/2.mp3');
  ids.stop.onclick();
  ids.player.onended();
  assert.equal(ids.player.src,'clips/2.mp3');
  const row=ids.list.children[0], flag=row.children[2].children[0],comment=row.children[3];
  flag.checked=true;flag.onchange();comment.value='앞부분 확인';comment.oninput();
  assert.equal(JSON.parse(Object.values(stored)[0])['1'].comment,'앞부분 확인');
  ids.export.onclick();
  const result=JSON.parse(await blobs[0].text());
  assert.equal(result.items[0].issue,true);
  assert.equal(result.items[0].comment,'앞부분 확인');
  ids.player.play=async()=>{throw Error('blocked');};
  ids.start.onclick();await new Promise(resolve=>setImmediate(resolve));
  assert.match(ids.status.textContent,/재생 실패/);
  console.log('Review UI logic passed');
});
