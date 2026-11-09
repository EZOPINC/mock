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
