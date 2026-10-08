/* Generic comparison dialogs: reusable by preparation and legacy design pages. */
(() => {
  function initComparisons(root = document) {
    root.querySelectorAll('[data-compare]').forEach(button => {
      if (button.dataset.comparisonReady) return;
      button.dataset.comparisonReady = 'true';
      button.addEventListener('click', () => {
        const dialog = document.getElementById(button.dataset.compare);
        if (!dialog || dialog.open) return;
        dialog.returnFocus = button;
        dialog.showModal();
        dialog.querySelector('[data-close-choice]')?.focus();
      });
    });
    root.querySelectorAll('.choice-dialog').forEach(dialog => {
      if (dialog.dataset.comparisonReady) return;
      dialog.dataset.comparisonReady = 'true';
      dialog.querySelector('[data-close-choice]')?.addEventListener('click', () => dialog.close());
      dialog.addEventListener('click', event => {
        const rect = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
      });
      dialog.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const focusable = [...dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]')].filter(el => el.getClientRects().length);
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
      dialog.addEventListener('close', () => dialog.returnFocus?.focus());
    });
  }
  window.FlickPondComparisons = {init: initComparisons};
  initComparisons();
  const panels = [...document.querySelectorAll('.prep-panel')];
  if (!panels.length) return;
  function route() {
    const hash = decodeURIComponent(location.hash.slice(1)) || 'security';
    const target = document.getElementById(hash);
    const panel = target?.closest('.prep-panel') || panels[0];
    panels.forEach(p => p.hidden = p !== panel);
    document.querySelectorAll('[data-prep-module]').forEach(a => {
      if (a.dataset.prepModule === panel.id) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    if (target && target !== panel) requestAnimationFrame(() => target.scrollIntoView({block: 'start'}));
    else window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);
  route();
  document.querySelector('[data-print-preparation]')?.addEventListener('click', () => window.print());
})();
