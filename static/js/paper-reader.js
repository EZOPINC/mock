// Native details and anchor links remain usable without JavaScript.
(() => {
  const panel = document.querySelector('.exam-paper-reader .paper-questions-panel');
  if (!panel) return;
  const compact = window.matchMedia('(max-width: 64rem)');
  const adapt = () => { panel.open = !compact.matches; };
  adapt();
  compact.addEventListener('change', adapt);
  panel.addEventListener('click', event => {
    const link = event.target.closest('[data-question-link]');
    if (!link) return;
    if (compact.matches) panel.open = false;
    document.getElementById(link.dataset.questionLink)?.focus({preventScroll: true});
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape' && compact.matches) {
      panel.open = false;
      panel.querySelector('summary').focus();
    }
  });
})();
