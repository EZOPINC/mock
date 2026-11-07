// Presentation only. Answer submission and locking remain server-controlled.
(() => {
  const page = document.querySelector('.ui-practice-session');
  if (!page) return;
  const panel = page.querySelector('.practice-palette-panel');
  if (panel && window.matchMedia('(max-width: 64rem)').matches) panel.open = false;
  if (new URLSearchParams(window.location.search).has('question')) {
    const question = page.querySelector('#practice-question');
    if (question) {
      question.focus({preventScroll: true});
      question.scrollIntoView({block: 'start'});
    }
  }
})();
