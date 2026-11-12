(() => {
  const preference = document.getElementById('mock-preferred-language');
  if (!preference) return;
  const language = JSON.parse(preference.textContent);
  if (!['en', 'bn'].includes(language)) return;
  document.querySelectorAll('.mock-question .translation-grid').forEach(grid => {
    const panels = [...grid.querySelectorAll('.translation-panel')];
    if (panels.some(panel => panel.lang === language)) {
      panels.forEach(panel => { panel.hidden = panel.lang !== language; });
    }
  });
})();
