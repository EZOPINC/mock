// Presentation only. Answer submission and locking remain server-controlled.
(() => {
  const page = document.querySelector('.ui-practice-session');
  if (!page) return;
  const answerForm = page.querySelector('.practice-answer');
  if (answerForm) {
    answerForm.addEventListener('change', event => {
      if (event.target.matches('input[type=radio]') && !answerForm.dataset.submitting) {
        answerForm.requestSubmit();
      }
    });
    answerForm.addEventListener('submit', event => {
      if (answerForm.dataset.submitting) {
        event.preventDefault();
        return;
      }
      answerForm.dataset.submitting = 'true';
      answerForm.setAttribute('aria-busy', 'true');
      answerForm.querySelector('.practice-selection-status').textContent = 'Checking your answer…';
    });
    answerForm.addEventListener('click', event => {
      if (answerForm.dataset.submitting) event.preventDefault();
    });
    // A browser back/forward-cache restore must not retain a submitting UI.
    window.addEventListener('pageshow', () => {
      delete answerForm.dataset.submitting;
      answerForm.removeAttribute('aria-busy');
    });
  }
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
