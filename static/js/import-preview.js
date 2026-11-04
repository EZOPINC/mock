// Never let unsaved browser edits masquerade as a server-validated preview.
const editForm = document.querySelector('#preview-edit-form');
const confirmForm = document.querySelector('form[action$="/confirm/"]');
let dirty = false;
if (editForm) {
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
