(() => {
  'use strict';
  const one = selector => document.querySelector(selector);
  const all = selector => [...document.querySelectorAll(selector)];
  const params = new URLSearchParams(location.search);
  let depth = 3;
  try { depth = Number(params.get('depth') || sessionStorage.getItem('flickpond-depth') || 3); } catch (_) { depth = Number(params.get('depth') || 3); }
  if (![1,2,3].includes(depth)) depth = 3;
  const hasDepth = !!one('.depth-controls');
  function applyDepth(value, remember = true) {
    depth = value;
    if (!hasDepth) return;
    all('[data-level]').forEach(el => { el.hidden = Number(el.dataset.level) > depth; });
    all('[data-depth]').forEach(el => el.setAttribute('aria-pressed', String(Number(el.dataset.depth) === depth)));
    one('.depth-hint').textContent = depth === 1 ? 'Basics are visible. Add Design when the main story feels familiar.' : depth === 2 ? 'Basics and design are visible. Add Details for implementation and evidence.' : 'All three levels are visible. You can trace every explanation back to its source.';
    one('.go-deeper').style.display = depth < 3 ? 'flex' : 'none';
    one('#next-depth').textContent = depth === 1 ? 'Add level 2 · Design' : 'Add level 3 · Details';
    // Keep the reading depth across file:// pages even if browser storage is unavailable.
    all('a[href]').forEach(a => {
      const href = a.getAttribute('href');
      if (!/^(basics|architecture|aws|delivery|code|data|security|quality|meeting)\.html(?:[?#]|$)/.test(href)) return;
      const target = new URL(href,location.href);
      target.searchParams.set('depth',String(depth));
      a.setAttribute('href',target.pathname.split('/').pop()+target.search+target.hash);
    });
    if (remember) { try { sessionStorage.setItem('flickpond-depth',String(depth)); } catch (_) {} }
  }
  function revealHash() {
    if (!hasDepth || !location.hash) return;
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (_) { return; }
    if (target?.dataset.level && Number(target.dataset.level) > depth) applyDepth(Number(target.dataset.level));
  }
  applyDepth(depth,params.has('depth')); revealHash();
  all('[data-depth]').forEach(b => b.addEventListener('click',() => applyDepth(Number(b.dataset.depth))));
  one('#next-depth')?.addEventListener('click',() => { const next = depth+1; applyDepth(next); one(`section[data-level="${next}"]`)?.scrollIntoView({block:'start'}); });
  window.addEventListener('hashchange',revealHash);
  const narrow = matchMedia('(max-width:860px)');
  const fitNavigation = () => { if (one('.chapter-nav')) one('.chapter-nav').open = !narrow.matches; };
  fitNavigation();
  narrow.addEventListener('change',fitNavigation);
  all('.visual [data-detail]').forEach(b => b.setAttribute('aria-pressed','false'));
  document.addEventListener('click',event => {
    const b = event.target.closest('.visual [data-detail]');
    if (!b) return;
    const figure = b.closest('.visual');
    figure.querySelectorAll('[data-detail]').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed','false'); });
    b.classList.add('on'); b.setAttribute('aria-pressed','true');
    const title = document.createElement('strong'); title.textContent = b.querySelector('.label').textContent + ': ';
    figure.querySelector('.detail').replaceChildren(title,document.createTextNode(b.dataset.detail));
  });
  function filterQuestions() {
    const query = one('#question-search').value.toLowerCase().trim();
    const chapter = one('#question-chapter').value;
    all('.question-item').forEach(el => { el.hidden = (!!chapter && el.dataset.chapter !== chapter) || !el.textContent.toLowerCase().includes(query); el.classList.remove('chosen'); });
    const count = all('.question-item:not([hidden])').length;
    one('#question-count').textContent = `${count} question${count === 1 ? '' : 's'} shown. Answer aloud, then open the answer.`;
    one('#no-questions').hidden = count !== 0;
  }
  if (one('#question-search')) {
    if (params.get('chapter')) one('#question-chapter').value = params.get('chapter');
    filterQuestions();
    one('#question-search').addEventListener('input',filterQuestions);
    one('#question-chapter').addEventListener('change',filterQuestions);
    one('#question-random').addEventListener('click',() => {
      const items = all('.question-item:not([hidden])');
      if (!items.length) return;
      all('.question-item').forEach(x => x.classList.remove('chosen'));
      const chosen = items[Math.floor(Math.random()*items.length)];
      chosen.classList.add('chosen'); chosen.querySelector('details').open = false;
      chosen.scrollIntoView({block:'start'}); chosen.querySelector('summary').focus({preventScroll:true});
    });
  }
  one('#glossary-search')?.addEventListener('input',event => {
    const query = event.target.value.toLowerCase().trim();
    all('.term').forEach(el => { el.hidden = !el.textContent.toLowerCase().includes(query); });
    one('#no-terms').hidden = all('.term:not([hidden])').length !== 0;
  });
  one('.print-button')?.addEventListener('click',() => window.print());
  let printState;
  window.addEventListener('beforeprint',() => { printState = all('details').map(d => [d,d.open]); all('details').forEach(d => { d.open = true; }); });
  window.addEventListener('afterprint',() => { printState?.forEach(([d,open]) => { d.open = open; }); });
})();
