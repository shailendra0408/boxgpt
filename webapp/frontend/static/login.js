const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const loginButton = document.getElementById('login-button');

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.classList.add('d-none');
  loginButton.disabled = true;
  loginButton.textContent = 'Signing in…';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        username: loginForm.username.value.trim(),
        password: loginForm.password.value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Unable to sign in.');
    window.location.assign('/app');
  } catch (error) {
    loginError.textContent = error.message;
    loginError.classList.remove('d-none');
  } finally {
    loginButton.disabled = false;
    loginButton.innerHTML = 'Sign in <span aria-hidden="true">→</span>';
  }
});
