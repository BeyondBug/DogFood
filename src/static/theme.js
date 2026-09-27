(() => {
  const key = 'beyondbug-theme';
  let theme = 'light';
  try { theme = localStorage.getItem(key) === 'dark' ? 'dark' : 'light'; } catch {}
  document.documentElement.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('[data-theme-toggle]');
    const update = () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      buttons.forEach(button => {
        button.setAttribute('aria-pressed', String(dark));
        button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
        button.querySelector('[data-theme-label]').textContent = dark ? 'Light mode' : 'Dark mode';
        button.querySelector('[data-theme-icon]').textContent = dark ? '☼' : '◐';
      });
    };
    buttons.forEach(button => button.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(key, next); } catch {}
      update();
    }));
    update();
  });
})();
