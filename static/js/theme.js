const themeToggle = document.querySelector('[data-theme-toggle]');
const storedTheme = window.localStorage.getItem('clearspend-theme');
const pageTheme = document.documentElement.dataset.theme;
const activeTheme = ['light', 'dark'].includes(pageTheme)
  ? pageTheme
  : (storedTheme === 'dark' ? 'dark' : 'light');

function applyTheme(theme) {
  document.documentElement.classList.toggle('dark-theme', theme === 'dark');
  document.body.classList.toggle('dark-theme', theme === 'dark');
  document.documentElement.style.colorScheme = theme;
}

applyTheme(activeTheme);
if (['light', 'dark'].includes(pageTheme)) window.localStorage.setItem('clearspend-theme', activeTheme);
themeToggle?.addEventListener('click', () => {
  const nextTheme = document.body.classList.contains('dark-theme') ? 'light' : 'dark';
  applyTheme(nextTheme);
  window.localStorage.setItem('clearspend-theme', nextTheme);
});
