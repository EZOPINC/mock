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
  let version = initial.version, position = initial.position, queue = [], saving = false;
  let failed = false, conflict = false, expired = false, leaving = false;
  let remaining = Date.parse(initial.deadline) - Date.parse(initial.server_now), synced = performance.now();
  const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  function indicators() {
    cards.forEach(card => {
      const answered = Boolean(card.querySelector('input[type=radio]:checked'));
      const review = card.querySelector('[data-review]').checked;
      const button = root.querySelector(`.mock-palette [data-goto="${card.dataset.order}"]`);
      button.classList.toggle('is-answered', answered);
      button.classList.toggle('is-review', review);
      button.setAttribute('aria-label', `Question ${card.dataset.order}, ${answered ? 'answered' : 'unanswered'}${review ? ', marked for review' : ''}`);
      if (Number(card.dataset.order) === position) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
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
          root.querySelectorAll('input, button').forEach(control => { control.disabled = true; });
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
  palette.forEach(button => button.addEventListener('click', () => show(Number(button.dataset.goto))));
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
      root.querySelectorAll('input, button').forEach(control => { control.disabled = true; });
      status.textContent = 'Time is up. Confirming finalization with the server. Only saved answers will count.';
      syncClock();
    } else if (expired && !conflict) {
      expired = false;
      root.querySelectorAll('input, button').forEach(control => { control.disabled = false; });
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
