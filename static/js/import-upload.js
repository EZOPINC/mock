const catalogueNode = document.querySelector('#import-catalogue');
if (catalogueNode) {
  const catalogue = JSON.parse(catalogueNode.textContent);
  const type = document.querySelector('#id_import_type');
  const authority = document.querySelector('#id_authority');
  const exam = document.querySelector('#id_exam');
  const subject = document.querySelector('#id_subject');
  const topic = document.querySelector('#id_topic');
  const previousOnly = new Set(['authority', 'exam', 'year', 'stage', 'paper', 'paper_name', 'part', 'session', 'acknowledge_existing']);
  const generalOnly = new Set(['exams', 'exam_mapping']);
  const restrict = (select, records, field, parent) => {
    const allowed = new Set(records.filter((record) => !parent || String(record[field]) === parent).map((record) => String(record.id)));
    [...select.options].forEach((option) => {
      option.disabled = Boolean(option.value && !allowed.has(option.value));
      option.hidden = option.disabled;
    });
    if (select.selectedOptions.length && select.selectedOptions[0].disabled) select.value = '';
  };
  const sync = () => {
    const previous = type.value === 'previous_year';
    const general = type.value === 'general';
    document.querySelectorAll('[data-import-field]').forEach((wrapper) => {
      const name = wrapper.dataset.importField;
      const visible = previousOnly.has(name) ? previous : generalOnly.has(name) ? general : true;
      wrapper.hidden = !visible;
      wrapper.querySelectorAll('input,select,textarea').forEach((input) => { input.disabled = !visible; });
      const required = ['file', 'import_type'].includes(name) || (previous && ['exam', 'year'].includes(name)) || (general && name === 'exams');
      const field = wrapper.querySelector('input,select,textarea');
      if (field) field.required = required;
      const note = wrapper.querySelector('.field-requirement');
      if (note) note.textContent = required ? 'Required' : 'Optional';
    });
    if (previous) {
      restrict(exam, catalogue.exams, 'authority_id', authority.value);
      restrict(document.querySelector('#id_paper'), catalogue.papers, 'exam_id', exam.value);
      restrict(document.querySelector('#id_stage'), catalogue.stages, 'exam_id', exam.value);
    }
    restrict(topic, catalogue.topics, 'subject_id', subject.value);
  };
  [type, authority, exam, subject].forEach((field) => field.addEventListener('change', sync));
  sync();
}
