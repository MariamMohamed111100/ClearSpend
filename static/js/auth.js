document.querySelectorAll('[data-toggle-password]').forEach((button) => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.togglePassword);
    const visible = input.type === 'text';
    input.type = visible ? 'password' : 'text';
    button.textContent = visible ? 'Show' : 'Hide';
  });
});

const password = document.getElementById('register-password');
const meter = document.querySelector('[data-password-meter]');
if (password && meter) {
  password.addEventListener('input', () => {
    const value = password.value;
    let score = 0;
    if (value.length >= 8) score += 1;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score += 1;
    if (/\d/.test(value) || /[^A-Za-z0-9]/.test(value)) score += 1;
    meter.style.width = `${score * 33.33}%`;
    meter.dataset.score = score;
  });
}
