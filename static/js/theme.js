// Apply before styles paint. Storage is optional; system preference is the fallback.
(() => {
  document.documentElement.classList.add('js');
  const key = 'mock-exam-theme';
  const choices = ['system', 'light', 'dark', 'sepia'];
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = localStorage.getItem(key) || 'system'; } catch (_) {}
  if (!choices.includes(preference)) preference = 'system';
  const apply = () => {
    document.documentElement.dataset.theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.querySelectorAll('[data-theme-select]').forEach(control => { control.value = preference; });
  };
  apply();
  system.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    preference = choices.includes(event.newValue) ? event.newValue : 'system';
    apply();
  });
  document.addEventListener('DOMContentLoaded', () => {
    // If the optional navigation enhancement failed to load, retain native links.
    const navigation = document.querySelector('#primary-navigation');
    if (navigation && !navigation.dataset.navigationReady) {
      navigation.hidden = false;
      navigation.dataset.navigationReady = 'true';
    }
    const controls = [...document.querySelectorAll('[data-theme-select]')];
    controls.forEach(control => { control.closest('.appearance-control').hidden = false; control.disabled = false; });
    apply();
    controls.forEach(control => control.addEventListener('change', () => {
      preference = choices.includes(control.value) ? control.value : 'system';
      let stored = true;
      try { localStorage.setItem(key, preference); } catch (_) { stored = false; }
      apply();
      document.querySelectorAll('[data-theme-status]').forEach(status => {
        status.textContent = `${control.selectedOptions[0].textContent} theme selected. ${stored ? 'Saved in this browser.' : 'Browser storage unavailable; applied for this page.'}`;
      });
    }));
  });
})();
