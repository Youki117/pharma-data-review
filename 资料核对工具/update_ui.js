(() => {
  if (document.getElementById('updateButton')) return;
  const button = document.createElement('button');
  button.id = 'updateButton';
  button.textContent = '版本';
  button.style.cssText = 'margin-left:auto;font:12px "Microsoft YaHei",sans-serif;border:1px solid var(--rule);border-radius:6px;padding:5px 10px;background:var(--surface);color:var(--muted);white-space:nowrap;cursor:pointer';
  const oldVersion = document.querySelector('.suitebar .version');
  if (oldVersion) oldVersion.replaceWith(button);
  else document.querySelector('header').append(button);
  const dialog = document.createElement('dialog');
  dialog.id = 'updateDialog';
  dialog.setAttribute('aria-labelledby', 'updateTitle');
  dialog.style.cssText = 'padding:24px;width:480px;max-width:calc(100vw - 32px);border:1px solid var(--rule);border-radius:12px;background:var(--surface);color:var(--ink);box-shadow:0 16px 60px #0003';
  dialog.innerHTML = '<h2 id="updateTitle" style="font-size:17px;margin:0 0 16px">软件更新</h2><p id="updateStatus" role="status"></p><pre id="updateNotes" style="font-family:inherit;font-size:12px;line-height:1.8;white-space:pre-wrap;max-height:40vh;overflow:auto"></pre><div style="display:flex;gap:10px;justify-content:flex-end;margin-top:20px"><button id="updateClose">关闭</button><button id="updateCheck">检查更新</button><button id="updateInstall" class="primary" hidden>更新并重启</button></div>';
  document.body.append(dialog);
  const status = dialog.querySelector('#updateStatus');
  const notes = dialog.querySelector('#updateNotes');
  const check = dialog.querySelector('#updateCheck');
  const install = dialog.querySelector('#updateInstall');
  for (const control of dialog.querySelectorAll('button')) control.style.cssText = 'font:inherit;border:1px solid var(--rule);border-radius:6px;padding:6px 12px;background:var(--surface);color:var(--ink);cursor:pointer';
  let current = null;
  async function refresh() {
    try {
      current = await window.pywebview.api.update_status();
      const available = current.stage === 'available';
      button.textContent = current.stage === 'installing' ? '正在更新…' : available ? '有更新 · v' + current.version : 'v' + current.current;
      button.title = current.message + '；点击查看更新';
      button.style.color = available ? 'var(--accent)' : 'var(--muted)';
      status.textContent = current.message;
      notes.textContent = current.notes || '';
      notes.hidden = !current.notes;
      check.disabled = ['checking', 'installing'].includes(current.stage);
      install.hidden = !available || !current.installable;
    } catch (_) {
      status.textContent = '更新状态暂不可用，可继续本地核对。';
      button.title = status.textContent;
    }
  }
  button.onclick = () => { dialog.showModal(); refresh(); };
  dialog.querySelector('#updateClose').onclick = () => dialog.close();
  check.onclick = async () => { await window.pywebview.api.check_updates(); await refresh(); };
  install.onclick = async () => {
    if (!confirm('更新到 v' + current.version + ' 并重启？\n程序将在关闭后替换原位置，并保留一份回退备份。已保存的报告不受影响；AI 密钥需重新填写。')) return;
    const result = await window.pywebview.api.install_update();
    if (!result.ok) status.textContent = result.error;
    else await refresh();
  };
  refresh(); setInterval(refresh, 1500);
})();
