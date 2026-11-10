// All options are rendered locally; the bound form also enforces subject scope.
document.addEventListener('DOMContentLoaded', () => {
  const subject = document.getElementById('id_subject');
  const selects = ['id_topic', 'id_additional_topics'].map(id => document.getElementById(id)).filter(Boolean);
  if (!subject) return;
  const filter = () => selects.forEach(select => {
    [...select.options].forEach(option => {
      if (!option.value) return;
      const allowed = option.dataset.subjectId === subject.value;
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (!allowed) option.selected = false;
    });
  });
  subject.addEventListener('change', filter);
  filter();
});
