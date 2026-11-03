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
    #guideDialog{position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;margin:0;padding:0;border:0;background:transparent;color:var(--ink);font:13px/1.6 "Segoe UI","Microsoft YaHei",sans-serif;overflow:hidden}
    #guideDialog::backdrop{background:transparent}
    #guideHighlight{position:fixed;z-index:1;border-radius:8px;box-shadow:0 0 0 9999px #0008,0 0 0 2px var(--accent);pointer-events:none;transition:top .15s,left .15s,width .15s,height .15s}
    #guideCard{position:fixed;z-index:2;width:330px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;padding:12px 14px;border:1px solid var(--rule);border-radius:10px;background:var(--surface);box-shadow:0 6px 24px #0005}
    #guideDialog h2{font-size:14px;line-height:1.6;margin:0 0 6px}#guideText{white-space:pre-line;margin:0}#guideCount{font-size:12px;color:var(--muted);margin-bottom:4px}
    #guideActions{display:flex;gap:8px;align-items:center;margin-top:12px}#guideActions button{font:inherit;font-size:12px;padding:5px 9px;border:1px solid var(--rule);border-radius:6px;background:var(--surface);color:var(--ink);cursor:pointer}#guideActions button:focus-visible,#guideButton:focus-visible{outline:2px solid var(--accent);outline-offset:3px}#guideActions button:disabled{opacity:.4;cursor:default}#guideActions #guideNext{background:var(--accent);color:var(--surface);border-color:var(--accent)}#guideSkip{margin-left:auto}#guideKeys{font-size:11px;color:var(--muted);margin-top:8px}
    @media(prefers-reduced-motion:reduce){#guideHighlight{transition:none}}
  `;
  document.head.append(style);
  const dialog = document.createElement('dialog');
  dialog.id = 'guideDialog';
  dialog.setAttribute('aria-labelledby', 'guideTitle');
  dialog.innerHTML = '<div id="guideHighlight" hidden></div><section id="guideCard"><div id="guideCount"></div><div aria-live="polite" aria-atomic="true"><h2 id="guideTitle"></h2><p id="guideText"></p></div><div id="guideActions"><button id="guideNext">下一步</button><button id="guideBack">上一步</button><button id="guideSkip">跳过引导</button></div><div id="guideKeys">回车操作当前按钮 · Esc 跳过</div></section>';
  document.body.append(dialog);
  const find = id => dialog.querySelector('#' + id);
  const api = window.pywebview.api;
  let steps = [], index = 0, originalTask = '', originalFocus = null, saving = false, timer = null;
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
    const card = find('guideCard');
    if (!element || !element.getClientRects().length) {
      highlight.hidden = false;
      Object.assign(highlight.style, {left:'50%', top:'50%', width:'0', height:'0'});
      card.style.left = Math.max(16, (innerWidth - card.offsetWidth) / 2) + 'px';
      card.style.top = Math.max(16, (innerHeight - card.offsetHeight) / 2) + 'px';
      return;
    }
    const rect = element.getBoundingClientRect();
    const offset = frame ? frame.getBoundingClientRect() : {left:0, top:0};
    const left = Math.max(4, rect.left + offset.left - 4), top = Math.max(4, rect.top + offset.top - 4);
    highlight.style.left = left + 'px'; highlight.style.top = top + 'px';
    highlight.style.width = Math.max(0, Math.min(rect.width + 8, innerWidth - left - 4)) + 'px';
    highlight.style.height = Math.max(0, Math.min(rect.height + 8, innerHeight - top - 4)) + 'px';
    highlight.hidden = false;
    const width = card.offsetWidth, height = card.offsetHeight, gap = 12, margin = 16;
    const bottom = Math.min(top + rect.height + 8, innerHeight - 4);
    const right = Math.min(left + rect.width + 8, innerWidth - 4);
    let x = left, y;
    if (bottom + gap + height <= innerHeight - margin) y = bottom + gap;
    else if (top - gap - height >= margin) y = top - gap - height;
    else if (left - gap - width >= margin) { x = left - gap - width; y = top; }
    else if (right + gap + width <= innerWidth - margin) { x = right + gap; y = top; }
    else { x = (innerWidth - width) / 2; y = (innerHeight - height) / 2; }
    card.style.left = Math.max(margin, Math.min(x, innerWidth - width - margin)) + 'px';
    card.style.top = Math.max(margin, Math.min(y, innerHeight - height - margin)) + 'px';
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
    find('guideNext').focus();
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
      if (dialog.open) return;
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
      index = 0; dialog.showModal(); render(); timer = setInterval(position, 400);
    } catch (_) { if (!automatic) alert('引导暂不可用，请重新打开工具。'); }
  }
  find('guideSkip').onclick = finish;
  find('guideBack').onclick = () => { if (index > 0 && !saving) { index--; render(); } };
  find('guideNext').onclick = () => { if (saving) return; if (index === steps.length - 1) finish(); else { index++; render(); } };
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish(); });
  dialog.addEventListener('close', () => { clearInterval(timer); timer = null; });
  button.onclick = () => start();
  window.addEventListener('resize', position);
  for (const frame of document.querySelectorAll('iframe')) frame.addEventListener('load', position);
  start(true);
})();
