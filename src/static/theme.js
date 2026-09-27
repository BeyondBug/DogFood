(() => {
  const key = 'beyondbug-theme';
  let theme = 'light';
  try { theme = localStorage.getItem(key) === 'dark' ? 'dark' : 'light'; } catch {}
  document.documentElement.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const back = document.querySelector('[data-back-link]');
    if (back) {
      const path = window.location.pathname;
      const eventId = path.split('/')[2];
      if (path === '/events') back.href = '/';
      else if (path === '/admin' || path === '/my/certificates' || path.startsWith('/organizer/') || path.startsWith('/judge/')) back.href = '/dashboard';
      else if ((path.startsWith('/workspace/') || path.startsWith('/vote/') || path.startsWith('/results/')) && eventId) back.href = `/events/${encodeURIComponent(eventId)}`;
      back.addEventListener('click', event => {
        try {
          const previous = new URL(document.referrer);
          if (history.length > 1 && previous.origin === window.location.origin && previous.href !== window.location.href &&
              previous.pathname !== '/account' && !previous.pathname.startsWith('/api/')) {
            event.preventDefault();
            history.back();
          }
        } catch {}
      });
    }
    const buttons = document.querySelectorAll('[data-theme-toggle]');
    const update = () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      buttons.forEach(button => {
        button.setAttribute('aria-pressed', String(dark));
        button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
        button.querySelector('[data-theme-label]').textContent = dark ? 'Light mode' : 'Dark mode';
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
