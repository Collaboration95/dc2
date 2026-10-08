(() => {
  const panels = [...document.querySelectorAll('.panel')];
  const steps = [...document.querySelectorAll('.step-article')];
  const stepButtons = [...document.querySelectorAll('[data-step]')];
  const navLinks = [...document.querySelectorAll('[data-panel]')];
  const key = 'team17-roadmap-review-v1';
  let reviewed = [];
  let persistent = true;
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    if (Array.isArray(value)) reviewed = value.filter(n => Number.isInteger(n) && n >= 0 && n < steps.length);
  } catch { persistent = false; }

  function updateProgress() {
    reviewed = [...new Set(reviewed)];
    document.querySelectorAll('[data-complete]').forEach(input => {
      input.checked = reviewed.includes(Number(input.dataset.complete));
    });
    stepButtons.forEach((button, i) => {
      button.classList.toggle('done', reviewed.includes(i));
      button.querySelector('.step-number').textContent = reviewed.includes(i) ? '✓' : String(i + 1).padStart(2, '0');
    });
    document.getElementById('progress-text').textContent = `${reviewed.length} of ${steps.length} steps reviewed`;
    document.getElementById('review-progress').value = reviewed.length;
    if (!persistent) document.getElementById('storage-note').textContent = 'Browser storage is unavailable. Review marks last for this session only.';
  }

  function route(focus = false) {
    const hash = location.hash.slice(1) || 'roadmap';
    const match = /^step-(\d+)$/.exec(hash);
    const index = match ? Math.min(steps.length - 1, Math.max(0, Number(match[1]) - 1)) : 0;
    const requested = match ? 'roadmap' : hash;
    const panel = panels.find(p => p.id === `panel-${requested}`) || panels[0];
    panels.forEach(p => { p.hidden = p !== panel; });
    navLinks.forEach(a => {
      if (`panel-${a.dataset.panel}` === panel.id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    document.getElementById('current-section').textContent = panel.getAttribute('aria-label');
    steps.forEach((step, i) => { step.hidden = i !== index; });
    stepButtons.forEach((button, i) => {
      if (i === index) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    if (focus && match) {
      const title = steps[index].querySelector('h2');
      title.focus({ preventScroll: true });
      if (window.innerWidth <= 850) steps[index].scrollIntoView({ block: 'start' });
    } else if (focus) {
      window.scrollTo(0, 0);
      const title = panel.querySelector('h1');
      if (title) { title.setAttribute('tabindex', '-1'); title.focus({ preventScroll: true }); }
    }
  }

  stepButtons.forEach(button => button.addEventListener('click', () => {
    location.hash = `step-${Number(button.dataset.step) + 1}`;
  }));
  document.querySelectorAll('[data-next]').forEach(button => button.addEventListener('click', () => {
    const next = Number(button.dataset.next) + 2;
    location.hash = next > steps.length ? 'submissions' : `step-${next}`;
  }));
  document.querySelectorAll('[data-prev]').forEach(button => button.addEventListener('click', () => {
    location.hash = `step-${Number(button.dataset.prev)}`;
  }));
  document.querySelectorAll('[data-complete]').forEach(input => input.addEventListener('change', () => {
    const index = Number(input.dataset.complete);
    reviewed = input.checked ? [...reviewed, index] : reviewed.filter(n => n !== index);
    try { localStorage.setItem(key, JSON.stringify(reviewed)); } catch { persistent = false; }
    updateProgress();
  }));
  document.getElementById('print').addEventListener('click', () => window.print());
  window.addEventListener('hashchange', () => route(true));
  updateProgress();
  route();
})();
