(() => {
  document.addEventListener('change', event => {
    const form = event.target.closest('.paper-practice-form');
    if (form && event.target.matches('input[type=radio]')) form.requestSubmit();
  });
  document.addEventListener('submit', async event => {
    const form = event.target.closest('.paper-practice-form');
    if (!form) return;
    event.preventDefault();
    if (form.dataset.saving) return;
    form.dataset.saving = 'true';
    const body = new FormData(form);
    const controls = [...form.querySelectorAll('input, button')];
    controls.forEach(control => { control.disabled = true; });
    const status = form.querySelector('.paper-practice-status');
    status.textContent = 'Checking answer...';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(form.action, {method: 'POST', body, credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'}, signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw new Error('Unable to check answer');
      form.closest('.paper-practice-question').innerHTML = await response.text();
    } catch (_) {
      status.textContent = 'Unable to check your answer. Select an option to try again, or reload the paper if it is no longer available.';
      controls.forEach(control => { control.disabled = false; });
      delete form.dataset.saving;
      form.querySelectorAll('input[type=radio]').forEach(input => { input.checked = false; });
    } finally { clearTimeout(timeout); }
  });
})();
