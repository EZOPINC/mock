(() => {
  const root = document.querySelector('.mock-execution');
  if (!root) return;
  const initial = JSON.parse(document.getElementById('attempt-clock').textContent);
  const cards = [...root.querySelectorAll('.mock-question')];
  const palette = [...root.querySelectorAll('[data-goto]')];
  const status = document.getElementById('mock-save-status');
  const clockStatus = document.getElementById('mock-clock-status');
  const retry = document.getElementById('mock-retry');
  const finish = document.getElementById('mock-finish');
  const csrf = root.querySelector('[name=csrfmiddlewaretoken]').value;
  // Presentation controls reuse the existing navigation and persistence paths.
  const counter = document.getElementById('mock-question-counter');
  const progress = document.getElementById('mock-progress');
  const answeredCount = document.getElementById('mock-answered-count');
  const remainingCount = document.getElementById('mock-remaining-count');
  const reviewCount = document.getElementById('mock-review-count');
  const sectionSelect = document.getElementById('mock-section');
  const sectionLabel = document.getElementById('mock-current-section');
  const palettePanel = document.getElementById('mock-palette-panel');
  const paletteToggle = root.querySelector('[data-palette-toggle]');
  const previousButton = root.querySelector('[data-current-prev]');
  const nextButton = root.querySelector('[data-current-next]');
  const compact = window.matchMedia('(max-width: 64rem)');
  let version = initial.version, position = initial.position, queue = [], saving = false;
  let failed = false, conflict = false, expired = false, leaving = false;
  let remaining = Date.parse(initial.deadline) - Date.parse(initial.server_now), synced = performance.now();
  const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  function indicators() {
    let answeredTotal = 0, reviewTotal = 0;
    cards.forEach(card => {
      const answered = Boolean(card.querySelector('input[type=radio]:checked'));
      const review = card.querySelector('[data-review]').checked;
      answeredTotal += Number(answered);
      reviewTotal += Number(review);
      const button = root.querySelector(`.mock-palette [data-goto="${card.dataset.order}"]`);
      button.classList.toggle('is-answered', answered);
      button.classList.toggle('is-review', review);
      button.setAttribute('aria-label', `Question ${card.dataset.order}, ${answered ? 'answered' : 'unanswered'}${review ? ', marked for review' : ''}${Number(card.dataset.order) === position ? ', current question' : ''}`);
      const state = button.querySelector('.mock-palette-state');
      if (state) state.textContent = review ? (answered ? '\u2713 !' : '!') : (answered ? '\u2713' : '\u2014');
      if (Number(card.dataset.order) === position) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
    if (counter) counter.textContent = `Question ${position} of ${cards.length}`;
    if (answeredCount) answeredCount.textContent = answeredTotal;
    if (remainingCount) remainingCount.textContent = cards.length - answeredTotal;
    if (reviewCount) reviewCount.textContent = reviewTotal;
    if (progress) { progress.value = answeredTotal; progress.textContent = `${answeredTotal} of ${cards.length} answered`; }
    const current = cards.find(card => Number(card.dataset.order) === position);
    if (sectionSelect && current) {
      sectionSelect.value = current.dataset.sectionId;
      if (sectionLabel) sectionLabel.textContent = sectionSelect.selectedOptions[0]?.textContent || '';
    }
    if (previousButton) previousButton.disabled = expired || conflict || position <= 1;
    if (nextButton) nextButton.disabled = expired || conflict || position >= cards.length;
  }
  function setCurrent(order, persist = true) {
    const changed = position !== order;
    position = order;
    indicators();
    if (persist && changed) enqueue({action: 'position', position: order});
  }
  function show(order, persist = true, focus = true) {
    const target = cards.find(card => Number(card.dataset.order) === order);
    if (!target) return;
    setCurrent(order, persist);
    if (focus) target.focus({preventScroll: true});
    if (focus || order > 1) target.scrollIntoView({block: 'start'});
  }
  function enqueue(payload) {
    if (expired || conflict) return;
    queue.push(payload);
    status.textContent = 'Saving changes...';
    pump();
  }
  async function request(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try { return await fetch(url, {...options, signal: controller.signal, credentials: 'same-origin', cache: 'no-store'}); }
    finally { clearTimeout(timeout); }
  }
  async function pump() {
    if (saving || failed || conflict || expired || !queue.length) return;
    saving = true;
    const item = queue[0];
    if (item.version === undefined) { item.version = version; item.token = token(); }
    for (let tries = 0; tries < 3; tries++) {
      try {
        const response = await request(root.dataset.saveUrl, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(item)});
        const data = await response.json();
        if (data.finalized) { leaving = true; window.location.assign(root.dataset.statusUrl.replace('status/', 'results/')); return; }
        if (response.status === 409) {
          conflict = true;
          status.textContent = 'Another request changed this attempt. Reload saved state before continuing; local unsaved changes have not been applied.';
          root.querySelectorAll('input, button, select').forEach(control => { control.disabled = true; });
          break;
        }
        if (!response.ok || !data.ok) throw new Error(data.error || 'Save failed');
        version = data.version;
        queue.shift();
        status.textContent = queue.length ? 'Saving changes...' : 'All changes saved.';
        break;
      } catch (error) {
        if (tries === 2) { failed = true; retry.hidden = false; status.textContent = 'Changes are not saved. Check your connection and retry before leaving.'; }
        else await new Promise(resolve => setTimeout(resolve, 1000 * (tries + 1)));
      }
    }
    saving = false;
    if (!failed && !conflict) pump();
  }
  cards.forEach(card => {
    card.addEventListener('focusin', () => setCurrent(Number(card.dataset.order)));
    card.addEventListener('change', () => {
      setCurrent(Number(card.dataset.order), false);
      enqueue({action: 'answer', question_id: Number(card.dataset.rowId), answer: card.querySelector('input[type=radio]:checked')?.value || '', review: card.querySelector('[data-review]').checked, position});
    });
    card.querySelector('[data-clear]').addEventListener('click', () => {
      card.querySelectorAll('input[type=radio]').forEach(input => { input.checked = false; });
      card.dispatchEvent(new Event('change'));
    });
  });
  palette.forEach(button => button.addEventListener('click', () => {
    if (compact.matches && button.closest('.mock-palette') && palettePanel) palettePanel.open = false;
    show(Number(button.dataset.goto));
  }));
  previousButton?.addEventListener('click', () => show(position - 1));
  nextButton?.addEventListener('click', () => show(position + 1));
  sectionSelect?.addEventListener('change', () => {
    const target = cards.find(card => card.dataset.sectionId === sectionSelect.value);
    if (target) {
      if (compact.matches && palettePanel) palettePanel.open = false;
      show(Number(target.dataset.order));
    }
  });
  if (palettePanel) {
    palettePanel.open = !compact.matches;
    const syncPaletteToggle = () => paletteToggle?.setAttribute('aria-expanded', String(palettePanel.open));
    palettePanel.addEventListener('toggle', syncPaletteToggle);
    syncPaletteToggle();
    compact.addEventListener('change', () => {
      const focusInside = palettePanel.contains(document.activeElement);
      palettePanel.open = !compact.matches;
      if (focusInside && !palettePanel.open) palettePanel.querySelector('summary').focus();
    });
    paletteToggle?.addEventListener('click', () => {
      palettePanel.open = !palettePanel.open;
      palettePanel.scrollIntoView({block: 'start'});
      palettePanel.querySelector('summary').focus({preventScroll: true});
    });
  }
  const toolbar = root.querySelector('.mock-toolbar');
  if (toolbar && 'ResizeObserver' in window) {
    new ResizeObserver(() => root.style.setProperty('--mock-toolbar-height', `${Math.ceil(toolbar.getBoundingClientRect().height)}px`)).observe(toolbar);
  }
  retry.addEventListener('click', () => { failed = false; retry.hidden = true; status.textContent = 'Retrying unsaved changes...'; pump(); });
  finish.addEventListener('click', async event => {
    event.preventDefault();
    if (failed || conflict) { status.textContent = 'Resolve unsaved changes before submitting.'; return; }
    finish.setAttribute('aria-disabled', 'true');
    while ((saving || queue.length) && !failed && !conflict && !expired) await new Promise(resolve => setTimeout(resolve, 100));
    finish.removeAttribute('aria-disabled');
    if (!failed && !conflict && !expired) { leaving = true; window.location.assign(finish.href); }
  });
  let checking = false;
  async function syncClock() {
    if (checking || leaving) return;
    checking = true;
    try {
      const response = await request(root.dataset.statusUrl);
      if (!response.ok) throw new Error('Clock unavailable');
      const data = await response.json();
      if (data.finalized) { leaving = true; window.location.assign(data.result_url); return; }
      remaining = Date.parse(data.deadline) - Date.parse(data.server_now);
      synced = performance.now();
      clockStatus.textContent = '';
    } catch (_) { clockStatus.textContent = 'Cannot reach the server. The deadline still applies; reconnect to confirm saved answers and finalization.'; }
    finally { checking = false; }
  }
  function tick() {
    const seconds = Math.max(0, Math.ceil((remaining - (performance.now() - synced)) / 1000));
    document.getElementById('mock-timer').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (!seconds) {
      expired = true;
      root.querySelectorAll('input, button, select').forEach(control => { control.disabled = true; });
      status.textContent = 'Time is up. Confirming finalization with the server. Only saved answers will count.';
      syncClock();
    } else if (expired && !conflict) {
      expired = false;
      root.querySelectorAll('input, button, select').forEach(control => { control.disabled = false; });
      indicators();
      pump();
    }
  }
  window.addEventListener('beforeunload', event => { if (!leaving && (saving || queue.length)) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('online', () => { syncClock(); if (!conflict) { failed = false; pump(); } });
  window.addEventListener('pageshow', syncClock);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncClock(); });
  show(position, false, false);
  tick();
  setInterval(tick, 1000);
  setInterval(syncClock, 15000);
})();
