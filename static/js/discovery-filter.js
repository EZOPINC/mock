// Progressive filtering of server-rendered cards only; no data requests.
(() => {
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase().trim();
  document.querySelectorAll('[data-discovery-filter]').forEach(control => {
    const list = document.getElementById(control.dataset.target);
    if (!list) return;
    const items = [...list.querySelectorAll('[data-discovery-item]')];
    if (!items.length) return;
    const input = control.querySelector('input[type=search]');
    const status = control.querySelector('[data-filter-status]');
    const empty = control.querySelector('[data-filter-empty]');
    const text = items.map(item => normalize(item.textContent));
    const update = () => {
      const terms = normalize(input.value).split(/\s+/).filter(Boolean);
      let visible = 0;
      items.forEach((item, index) => {
        item.hidden = !terms.every(term => text[index].includes(term));
        if (!item.hidden) visible++;
      });
      status.textContent = `Showing ${visible} of ${items.length} items.`;
      empty.hidden = visible !== 0;
    };
    input.addEventListener('input', update);
    control.querySelector('[data-clear-filter]').addEventListener('click', () => {
      input.value = '';
      update();
      input.focus();
    });
    control.hidden = false;
    update();
  });
})();
