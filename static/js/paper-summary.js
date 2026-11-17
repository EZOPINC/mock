// Progressive enhancement: server-rendered subject counts work without JavaScript.
document.querySelectorAll('[data-paper-breakdown]').forEach(root => {
  const rows = [...root.querySelectorAll('[data-subject-count]')];
  const counts = rows.map(row => Number(row.dataset.subjectCount));
  if (counts.some(count => !Number.isFinite(count) || count < 0)) return;
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!total) return;
  const palette = ['var(--ui-accent)', 'var(--ui-chart-2)', 'var(--ui-chart-3)', 'var(--ui-chart-4)', 'var(--ui-chart-5)', 'var(--ui-chart-6)'];
  let position = 0;
  const segments = rows.map((row, index) => {
    const color = palette[index % palette.length];
    const start = position;
    position += counts[index] / total * 100;
    const swatch = row.querySelector('.paper-subject-swatch');
    swatch.style.backgroundColor = color;
    swatch.hidden = false;
    row.querySelector('[data-subject-percent]').textContent = `${(counts[index] / total * 100).toFixed(1)}%`;
    return `${color} ${start}% ${position}%`;
  });
  const chart = root.querySelector('[data-subject-chart]');
  chart.style.background = `conic-gradient(${segments.join(',')})`;
  root.querySelector('[data-subject-total]').textContent = total;
  chart.hidden = false;
});
