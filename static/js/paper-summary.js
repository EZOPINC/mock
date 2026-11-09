// Progressive enhancement: server-rendered subject counts work without JavaScript.
document.querySelectorAll('[data-paper-breakdown]').forEach(root => {
  const rows = [...root.querySelectorAll('[data-subject-count]')];
  const counts = rows.map(row => Number(row.dataset.subjectCount));
  if (counts.some(count => !Number.isFinite(count) || count < 0)) return;
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!total) return;
  const palette = ['#087f79', '#657db5', '#c78642', '#a56791', '#628943', '#b95b57'];
  let position = 0;
  const segments = rows.map((row, index) => {
    const color = palette[index] || `hsl(${(index * 137.508) % 360} 45% 44%)`;
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
