(() => {
  if (document.getElementById('updateBar')) return;
  const bar = document.createElement('div');
  bar.id = 'updateBar';
  bar.style.cssText = 'display:flex;align-items:center;gap:12px;flex-shrink:0;padding:5px 20px;border-bottom:1px solid var(--rule);background:var(--surface);color:var(--muted);font:12px/1.6 "Microsoft YaHei",sans-serif';
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  status.style.flex = '1';
  const check = document.createElement('button'); check.textContent = '检查更新';
  const install = document.createElement('button'); install.textContent = '更新并重启'; install.hidden = true;
  const details = document.createElement('button'); details.textContent = '更新说明'; details.hidden = true;
  for (const button of [check, details, install]) button.style.cssText = 'font:inherit;border:1px solid var(--rule);border-radius:5px;padding:2px 8px;color:var(--ink);background:var(--surface);cursor:pointer';
  bar.append(status, check, details, install);
  (document.querySelector('.suitebar') || document.querySelector('header')).after(bar);
  let current = null;
  async function refresh() {
    try {
      current = await window.pywebview.api.update_status();
      status.textContent = 'v' + current.current + ' · ' + current.message;
      const working = ['checking', 'installing'].includes(current.stage);
      check.disabled = working;
      install.hidden = current.stage !== 'available' || !current.installable;
      details.hidden = current.stage !== 'available';
    } catch (_) { status.textContent = '更新状态暂不可用；本地核对可继续使用。'; }
  }
  check.onclick = async () => { await window.pywebview.api.check_updates(); await refresh(); };
  details.onclick = () => alert(current.notes || '本次未附更新说明。');
  install.onclick = async () => {
    if (!confirm('更新到 v' + current.version + ' 并重启？\n请先查看或保存当前结果。会话中的 AI 密钥需在新版重新填写；旧程序和已保存的报告会保留。')) return;
    const result = await window.pywebview.api.install_update();
    if (!result.ok) alert(result.error);
    await refresh();
  };
  refresh(); setInterval(refresh, 1000);
})();
