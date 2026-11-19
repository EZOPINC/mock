document.querySelectorAll('[data-review-taxonomy]').forEach(form => {
  const { subject, module, chapter, topic } = form.elements;
  const filter = (select, parents) => {
    const selected = select.value;
    for (const option of select.options) {
      if (!option.value) continue;
      const visible = Object.entries(parents).every(([name, parent]) =>
        !parent.value || option.dataset[`${name}Id`] === parent.value
      );
      option.hidden = !visible;
      option.disabled = !visible;
      if (!visible && option.value === selected) select.value = '';
    }
  };
  const update = () => {
    filter(module, { subject });
    filter(chapter, { subject, module });
    filter(topic, { subject, module, chapter });
  };
  [subject, module, chapter].forEach(select => select.addEventListener('change', update));
  update();
});
