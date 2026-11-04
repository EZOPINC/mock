// Progressive enhancements; forms, solutions, and anchor navigation work without JS.
document.querySelectorAll('input[type="password"]').forEach((input) => {
  const wrapper = document.createElement('div');
  wrapper.className = 'password-wrap';
  input.before(wrapper);
  wrapper.append(input);
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'password-toggle';
  toggle.textContent = 'Show';
  toggle.setAttribute('aria-controls', input.id);
  toggle.setAttribute('aria-pressed', 'false');
  const label = document.querySelector(`label[for="${input.id}"]`);
  toggle.setAttribute('aria-label', `Show ${label ? label.textContent.replace(/:$/, '') : 'password'}`);
  toggle.addEventListener('click', () => {
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    toggle.textContent = visible ? 'Hide' : 'Show';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${label ? label.textContent.replace(/:$/, '') : 'password'}`);
  });
  wrapper.append(toggle);
});

const profileMenu = document.querySelector('.profile-menu');
if (profileMenu) {
  profileMenu.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      profileMenu.open = false;
      profileMenu.querySelector('summary').focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (!profileMenu.contains(event.target)) profileMenu.open = false;
  });
}

const questions = [...document.querySelectorAll('[data-question-index]')];
const links = [...document.querySelectorAll('[data-question-link]')];
questions.forEach((question, index) => {
  [['[data-previous-question]', questions[index - 1]], ['[data-next-question]', questions[index + 1]]].forEach(([selector, target]) => {
    const link = question.querySelector(selector);
    if (link && target) {
      link.href = `#${target.id}`;
      link.hidden = false;
    }
  });
});

function setCurrentQuestion(question) {
  links.forEach((link) => {
    if (link.dataset.questionLink === question.id) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  const progress = document.querySelector('.reader-progress');
  if (progress) progress.textContent = `Question ${question.dataset.questionIndex} of ${questions.length}`;
}

if (questions.length) {
  setCurrentQuestion(questions[0]);
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) setCurrentQuestion(visible[0].target);
    }, { rootMargin: '-15% 0px -55% 0px', threshold: 0 });
    questions.forEach((question) => observer.observe(question));
  }
}
