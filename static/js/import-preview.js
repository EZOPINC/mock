// Never let unsaved browser edits masquerade as a server-validated preview.
const editForm = document.querySelector('#preview-edit-form');
const confirmForm = document.querySelector('form[action$="/confirm/"]');
let dirty = false;
if (editForm) {
  document.querySelectorAll('.inline-taxonomy-form').forEach(form => {
    form.addEventListener('submit', event => {
      if (!dirty) return;
      event.preventDefault();
      const message = document.querySelector('[data-taxonomy-status]');
      if (message) message.textContent = 'Save page & Revalidate your row edits before adding a subject or topic.';
      editForm.querySelector('button[type=submit]')?.focus();
    });
  });
  editForm.addEventListener('input', () => {
    dirty = true;
    const button = confirmForm && confirmForm.querySelector('button');
    if (button) {
      button.disabled = true;
      button.textContent = 'Save & revalidate edits before confirming';
    }
  });
  editForm.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', (event) => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
}

const grid = document.querySelector('.preview-table');
const cellDialog = document.querySelector('#import-cell-dialog');
if (grid && cellDialog && typeof cellDialog.showModal === 'function') {
  const editor = cellDialog.querySelector('textarea');
  const apply = cellDialog.querySelector('button[value=apply]');
  let selected;
  const openCell = event => {
    const cell = event.target.closest('td textarea, .grid-cell-value');
    if (!cell || (event.type === 'keydown' && (event.key !== 'Enter' || event.shiftKey))) return;
    event.preventDefault();
    selected = cell;
    const editable = cell instanceof HTMLTextAreaElement;
    editor.value = editable ? cell.value : cell.textContent;
    editor.readOnly = !editable;
    apply.hidden = !editable;
    cellDialog.querySelector('h2').textContent = editable ? cell.labels[0].textContent : cell.dataset.gridLabel;
    cellDialog.returnValue = '';
    cellDialog.showModal();
    editor.focus();
  };
  grid.addEventListener('dblclick', openCell);
  grid.addEventListener('keydown', openCell);
  cellDialog.addEventListener('close', () => {
    if (cellDialog.returnValue === 'apply' && !editor.readOnly && selected.value !== editor.value) {
      selected.value = editor.value;
      selected.dispatchEvent(new Event('input', { bubbles: true }));
    }
    selected?.focus();
  });
}
