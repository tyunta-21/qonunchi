(function () {
  const f = document.getElementById('tocFilter'), list = document.getElementById('tocList');
  const norm = s => s.toLowerCase().replace(/[ʻʼ‘’`']/g, '');
  const arts = [...document.querySelectorAll('.art')];
  function apply() {
    const q = norm(f.value.trim());
    const words = q.split(/\s+/).filter(w => w.length > 2).map(w => w.length > 5 ? w.slice(0, w.length - 3) : w);
    list.querySelectorAll('a').forEach(a => {
      if (!words.length) { a.hidden = false; return; }
      const art = document.getElementById('a' + a.dataset.id);
      const txt = norm(a.textContent + ' ' + (art ? art.textContent : ''));
      a.hidden = !words.some(w => txt.includes(w));
    });
  }
  f.addEventListener('input', apply); apply();
  // подсветка текущей статьи в оглавлении
  const links = {}; list.querySelectorAll('a').forEach(a => links['a' + a.dataset.id] = a);
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { list.querySelectorAll('a.cur').forEach(x => x.classList.remove('cur'));
      const l = links[e.target.id]; if (l) { l.classList.add('cur'); } }
  }), {rootMargin: '0px 0px -80% 0px'});
  arts.forEach(a => io.observe(a));
})();
