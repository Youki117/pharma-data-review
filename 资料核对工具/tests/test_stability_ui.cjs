// Run the actual page script; model only DOM and the native bridge boundary.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../../本地对账工具/ui.html'), 'utf8');

function page() {
  const elements = new Map();
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) {
    elements.set(id, {value: '', hidden: false, disabled: false, style: {}, dataset: {},
      classList: {toggle() {}, add() {}, remove() {}}, addEventListener() {},
      querySelectorAll() {return [];}, querySelector() {return null;}});
  }
  const wrap = elements.get('wrap');
  Object.defineProperty(wrap, 'innerHTML', {set(value) {
    this.markup = value;
    // Welcome content is a child of wrap and is destroyed by innerHTML.
    elements.delete('empty');
  }});
  let timer, starts = 0, failure = '';
  const result = {products: [], issues: [], summary: [], levels: [], tiers: [], health: {blocking: [], notes: []}};
  const api = {version: async () => ({version: 'test'}),
    start: async () => {starts++; if (failure === 'start') throw Error('bridge'); return {ok: failure !== 'reject', error: 'invalid'};},
    progress: async () => {if (failure === 'progress') throw Error('bridge'); return {stage: 'done'};},
    results: async () => result};
  const context = vm.createContext({window: {pywebview: {api}},
    document: {querySelector: selector => elements.get(selector.slice(1)) || null},
    setInterval: fn => {timer = fn; return 1;}, clearInterval: () => {timer = null;},
    confirm: () => false, console});
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  return {elements, context, starts: () => starts, fail: value => {failure = value;},
    async run() {elements.get('path').value = 'selected-folder'; await elements.get('go').onclick();},
    async poll() {if (timer) await timer();}};
}

(async () => {
  const p = page();
  await p.run(); await p.poll();
  assert.equal(p.elements.has('empty'), false);
  vm.runInContext("LEVEL='previous-level';GID='previous-group';VIEW='all'", p.context);
  p.elements.get('q').value = 'previous search';
  await p.run(); await p.poll();
  assert.equal(p.starts(), 2, 'second run must reach the backend');
  assert.equal(p.elements.get('go').disabled, false);
  assert.equal(p.elements.get('q').value, '');
  assert.equal(vm.runInContext("LEVEL===null&&GID===null&&VIEW==='sum'", p.context), true);
  for (const failure of ['start', 'reject', 'progress']) {
    p.fail(failure); await p.run(); await p.poll();
    assert.equal(p.elements.get('go').disabled, false, failure);
    assert.equal(p.elements.get('pick').disabled, false, failure);
    assert.equal(p.elements.get('err').hidden, false, failure);
    p.fail(''); await p.run(); await p.poll();
    assert.equal(p.elements.get('go').disabled, false, 'retry after ' + failure);
  }
  console.log('PASS: repeat, fresh filters, start failure, rejection, progress failure, recovery');
})().catch(error => {console.error(error); process.exitCode = 1;});
