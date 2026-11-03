(() => {
  if (document.getElementById('guideButton')) return;
  const suite = !!document.querySelector('.suitebar');
  const button = document.createElement('button');
  button.id = 'guideButton';
  button.textContent = '使用引导';
  button.title = '重新查看资料导入与核对结果的使用步骤';
  button.style.cssText = 'font:inherit;font-size:12px;padding:5px 10px;white-space:nowrap;border:1px solid var(--rule);border-radius:6px;background:var(--surface);color:var(--muted);cursor:pointer';
  document.getElementById('updateButton').before(button);
  const style = document.createElement('style');
  style.textContent = `
    #guideDialog{position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;margin:0;padding:0;border:0;background:transparent;color:var(--ink);font:13px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}
    #guideDialog::backdrop{background:#08192188}
    #guideHighlight{position:fixed;border:2px solid #80d3e9;border-radius:8px;box-shadow:0 0 0 3px #fff9;pointer-events:none}
    #guideCard{position:fixed;right:28px;bottom:28px;width:400px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;padding:24px;border:1px solid var(--rule);border-radius:14px;background:var(--surface);box-shadow:0 14px 60px #0004}
    #guideDialog h2{font-size:19px;line-height:1.5;margin:8px 0 12px}#guideText{white-space:pre-line;margin:0 0 24px}#guideCount{font-size:12px;color:var(--muted)}
    #guideActions{display:flex;gap:8px;align-items:center}#guideActions button{font:inherit;padding:6px 12px;border:1px solid var(--rule);border-radius:6px;background:var(--surface);color:var(--ink);cursor:pointer}#guideActions button:focus-visible,#guideButton:focus-visible{outline:2px solid var(--accent);outline-offset:3px}#guideActions button:disabled{opacity:.4;cursor:default}#guideActions #guideNext{background:var(--accent);color:var(--surface);border-color:var(--accent)}#guideSkip{margin-right:auto}
    @media(max-width:800px){#guideCard{right:16px;bottom:16px;padding:20px}}
  `;
  document.head.append(style);
  const dialog = document.createElement('dialog');
  dialog.id = 'guideDialog';
  dialog.setAttribute('aria-labelledby', 'guideTitle');
  dialog.innerHTML = '<div id="guideHighlight" hidden></div><section id="guideCard"><div id="guideCount"></div><div aria-live="polite" aria-atomic="true"><h2 id="guideTitle"></h2><p id="guideText"></p></div><div id="guideActions"><button id="guideSkip">跳过</button><button id="guideBack">上一步</button><button id="guideNext">下一步</button></div></section>';
  document.body.append(dialog);
  const find = id => dialog.querySelector('#' + id);
  const api = window.pywebview.api;
  let steps = [], index = 0, originalTask = '', originalFocus = null, saving = false;
  const imports = {
    method: ['方法验证：一份报告配一份计算表', '#methodInputs', '选择或拖入一份 .docx 验证报告和对应的 .xlsx 计算表。'],
    stability: ['稳定性：导入整套资料目录', '#path', '选择或拖入存放稳定性汇总表与原始检验报告的文件夹，工具会递归查找。\n.doc 报告需要本机的转换程序；读取或转换失败会列在覆盖说明中。'],
    content: ['内容一致性：导入相关 Word', '#contentInputs', '添加或拖入 1～10 份相关 .docx，检查正文、表格及跨文件内容差异。']
  };
  function step(task, title, selector, text) { return {task, title, selector, text}; }
  function target() {
    const current = steps[index];
    const frame = suite && current.task ? document.getElementById('page-' + current.task) : null;
    const doc = frame ? frame.contentDocument : document;
    return {frame, element: doc?.querySelector(current.selector)};
  }
  function position() {
    if (!dialog.open) return;
    const {frame, element} = target();
    const highlight = find('guideHighlight');
    if (!element || !element.getClientRects().length) { highlight.hidden = true; return; }
    const rect = element.getBoundingClientRect();
    const offset = frame ? frame.getBoundingClientRect() : {left:0, top:0};
    const left = Math.max(4, rect.left + offset.left - 4), top = Math.max(4, rect.top + offset.top - 4);
    highlight.style.left = left + 'px'; highlight.style.top = top + 'px';
    highlight.style.width = Math.max(0, Math.min(rect.width + 8, innerWidth - left - 4)) + 'px';
    highlight.style.height = Math.max(0, Math.min(rect.height + 8, innerHeight - top - 4)) + 'px';
    highlight.hidden = false;
    const card = find('guideCard');
    card.style.top = ''; card.style.bottom = '';
    // 底部操作区需在浮层之外可见。
    if (top > innerHeight * .6) { card.style.top = '28px'; card.style.bottom = 'auto'; }
  }
  function render() {
    const current = steps[index];
    if (suite && current.task) activate(current.task);
    find('guideTitle').textContent = current.title;
    find('guideText').textContent = current.text;
    find('guideCount').textContent = `使用引导 · ${index + 1} / ${steps.length}`;
    find('guideBack').disabled = index === 0;
    find('guideNext').textContent = index === steps.length - 1 ? '完成引导' : '下一步';
    position();
  }
  async function finish() {
    if (saving) return;
    saving = true;
    try {
      const result = await api.guide_complete();
      dialog.close();
      if (suite && originalTask) activate(originalTask);
      originalFocus?.focus();
      if (!result.ok) alert(result.error);
    } catch (_) {
      dialog.close();
      if (suite && originalTask) activate(originalTask);
      originalFocus?.focus();
      alert('引导状态未能保存，下次打开仍会提示。');
    } finally { saving = false; }
  }
  async function start(automatic = false) {
    if (dialog.open) return;
    try {
      const state = await api.guide_status();
      if (automatic && state.seen) return;
      if (state.busy) { if (!automatic) alert('请等待当前核对或更新结束后再查看引导。'); return; }
      const documents = [document, ...[...document.querySelectorAll('iframe')].map(f => f.contentDocument).filter(Boolean)];
      if (documents.some(doc => doc.querySelector('dialog[open]'))) return;
      originalTask = suite ? document.querySelector('[data-task][aria-selected=true]').dataset.task : '';
      originalFocus = document.activeElement;
      steps = suite ? [step('', '先选择这次要核对什么', '.tabs', '方法验证：报告与计算表。\n稳定性资料：汇总表与检验报告。\n内容一致性：单份或多份 Word 的内容差异。')] : [];
      for (const task of suite ? ['method', 'stability', 'content'] : [state.product]) {
        const item = step(task, ...imports[task]);
        if (suite && task !== 'stability') item.text += '\n多批资料可用“批量导入”：按一级子文件夹各分一批，递归读取内部文件；先预览批次清单再启动。';
        steps.push(item);
      }
      const task = suite ? 'content' : state.product;
      steps.push(step(task, '可直接使用，也可启用 AI', '#settingsButton', '不配置 AI 也能运行本地筛选。\n在“设置”中填写密钥后，方法验证和内容一致性会自动调用 AI；解析文本会发送至所设接口并使用账户额度。密钥仅保留在本次运行内。\n稳定性逐值对账使用本地规则。'));
      steps.push(step(task, '资料选好后，开始核对', task === 'content' ? '#contentGo' : '#go', '点击“开始核对”，完成后按优先级查看结果。\n如果出现读取失败、AI 未完成或覆盖限制，先查看提示；零候选也不等于资料已全部审核通过。'));
      steps.push(step(task, '先看必看，再回查原文', 'footer', '先处理“必看”，再看“需确认”，其他项目按需抽查。点击问题提要可查看双边证据与原文位置。\n用“完整报告”或“结果文件夹”查看已保存的报告。以后可随时点击右上角“使用引导”重新查看。'));
      index = 0; dialog.showModal(); render(); find('guideNext').focus();
    } catch (_) { if (!automatic) alert('引导暂不可用，请重新打开工具。'); }
  }
  find('guideSkip').onclick = finish;
  find('guideBack').onclick = () => { if (index > 0 && !saving) { index--; render(); } };
  find('guideNext').onclick = () => { if (saving) return; if (index === steps.length - 1) finish(); else { index++; render(); } };
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish(); });
  button.onclick = () => start();
  window.addEventListener('resize', position);
  for (const frame of document.querySelectorAll('iframe')) frame.addEventListener('load', position);
  start(true);
})();
