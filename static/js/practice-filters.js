/* Counts and ancestry only. Eligibility is always revalidated by the server. */
(() => {
  "use strict";
  const form = document.querySelector("[data-practice-filters]");
  const payload = document.getElementById("practice-taxonomy-options");
  if (!form || !payload) return;
  const catalogue = JSON.parse(payload.textContent);
  const levels = ["part", "module", "chapter", "topic"];
  const selects = levels.map((level) => form.elements.namedItem(level));
  const count = form.elements.namedItem("count");
  const status = form.querySelector("[data-practice-pool]");
  const start = form.querySelector("[data-practice-start]");
  const total = Number(form.dataset.total);

  function refresh() {
    const chosen = {};
    let available = total;
    levels.forEach((level, index) => {
      const select = selects[index];
      const previous = select.value;
      const options = catalogue[level].filter((node) => Object.entries(chosen).every(
        ([parent, id]) => String(node.ancestors[parent] || "") === id));
      options.sort((a, b) => a.name.localeCompare(b.name));
      select.replaceChildren(new Option(`All ${level}s`, ""));
      options.forEach((node) => select.add(new Option(`${node.name} (${node.count})`, String(node.id))));
      const selected = options.find((node) => String(node.id) === previous);
      if (selected) {
        select.value = previous;
        chosen[level] = previous;
        available = selected.count;
      }
      select.disabled = !options.length;
    });
    const previousCount = count.value;
    count.replaceChildren();
    [10, 20, 30, 50].filter((size) => size <= available).forEach((size) => count.add(new Option(String(size), String(size))));
    count.add(new Option(`Available count (${available})`, "available"));
    count.value = [...count.options].some((option) => option.value === previousCount) ? previousCount : "available";
    status.textContent = available ? `${available} distinct eligible questions in this selection.` : "No eligible questions. Choose another subject or check back later.";
    start.disabled = available === 0;
  }
  selects.forEach((select) => select.addEventListener("change", refresh));
  refresh();
})();
