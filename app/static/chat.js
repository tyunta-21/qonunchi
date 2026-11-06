(function () {
  const T = window.T, lang = document.body.dataset.lang;
  const esc = s => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // простой и безопасный Markdown: **жирный**, списки, абзацы, ссылки [n]
  function md(text, srcs) {
    const byN = {}; (srcs || []).forEach(s => byN[s.n] = s);
    const inline = s => esc(s)
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/\[(\d+)\]/g, (m, n) => byN[n] ? `<a class="cite" href="${byN[n].url}" title="${esc(byN[n].heading)}">${n}</a>` : m);
    let html = '', list = false;
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      const li = line.match(/^([-*•]|\d+[.)])\s+(.*)/);
      if (li) { if (!list) { html += '<ul>'; list = true; } html += '<li>' + inline(li[2]) + '</li>'; continue; }
      if (list) { html += '</ul>'; list = false; }
      if (line) html += '<p>' + inline(line.replace(/^#+\s*/, '')) + '</p>';
    }
    if (list) html += '</ul>';
    return html;
  }

  function setup(root) {
    const log = root.querySelector('[data-log]'), form = root.querySelector('[data-form]');
    const input = root.querySelector('[data-input]'), btn = form.querySelector('button');
    let history = [];
    const key = 'qonunchi-chat-' + lang;
    try { history = JSON.parse(sessionStorage.getItem(key) || '[]'); } catch (e) {}

    function add(role, html) {
      const ex = root.querySelector('[data-examples]'); if (ex) ex.remove();
      const m = document.createElement('div'); m.className = 'msg ' + role;
      m.innerHTML = '<div class="bubble">' + html + '</div>';
      log.appendChild(m); log.scrollTop = log.scrollHeight; return m;
    }
    function renderBot(d) {
      let h = md(d.answer, d.sources);
      if (d.sources && d.sources.length) {
        h += `<div class="srcs"><b>${T.ai_sources}</b><ol>` + d.sources.map(s =>
          `<li value="${s.n}"><a href="${s.url}">${esc(s.heading)}</a> <span class="dt">— ${esc(s.doc_title)}${s.active ? '' : ' · ' + T.inactive_badge}</span>` +
          (s.src_url ? ` <a href="${s.src_url}" target="_blank" rel="noopener" class="dt">lex.uz ↗</a>` : '') + '</li>').join('') + '</ol></div>';
      }
      h += `<div class="disc">${esc(d.disclaimer || '')}</div>`;
      add('bot', h);
    }
    history.forEach(h => h.role === 'user' ? add('user', esc(h.content)) : renderBot(h.view));

    async function ask(q) {
      q = q.trim(); if (!q) return;
      add('user', esc(q)); input.value = ''; btn.disabled = true;
      const wait = add('bot', `<span class="typing">${T.ai_thinking}</span>`);
      try {
        const r = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question: q, lang, history: history.map(h => ({role: h.role, content: h.content}))})});
        const d = await r.json(); wait.remove();
        if (!r.ok) { add('bot', esc(d.error || T.ai_error)); return; }
        renderBot(d);
        history.push({role: 'user', content: q}, {role: 'assistant', content: d.answer, view: d});
        history = history.slice(-12);
        try { sessionStorage.setItem(key, JSON.stringify(history)); } catch (e) {}
      } catch (e) { wait.remove(); add('bot', esc(T.ai_error)); }
      finally { btn.disabled = false; input.focus(); }
    }
    form.addEventListener('submit', e => { e.preventDefault(); ask(input.value); });
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input.value); } });
    input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = input.scrollHeight + 'px'; });
    root.querySelectorAll('.ex').forEach(b => b.addEventListener('click', () => ask(b.textContent)));
    root.ask = ask;
    root.reset = () => { history = []; try { sessionStorage.removeItem(key); } catch (e) {} location.href = location.pathname; };
  }

  document.querySelectorAll('[data-chat]').forEach(setup);

  const fab = document.getElementById('chatFab'), panel = document.getElementById('chatPanel');
  if (fab) {
    fab.onclick = () => { panel.hidden = false; fab.hidden = true; panel.querySelector('[data-input]').focus(); };
    document.getElementById('chatClose').onclick = () => { panel.hidden = true; fab.hidden = false; };
  }
  const nc = document.getElementById('newChat');
  if (nc) nc.onclick = () => document.querySelector('[data-chat]').reset();
  const pre = new URLSearchParams(location.search).get('q');
  if (pre && location.pathname.endsWith('/assistant')) {
    const c = document.querySelector('[data-chat]'); c.querySelector('[data-input]').value = pre;
  }
})();
