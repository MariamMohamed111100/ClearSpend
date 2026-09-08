const form = document.getElementById('insight-form');
const resultBox = document.getElementById('result');
const loading = document.getElementById('loading');

if (form) {
  function addRepeatRow(container, markup) {
    container.insertAdjacentHTML('beforeend', markup);
  }

  document.querySelector('[data-add-category]')?.addEventListener('click', () => {
    addRepeatRow(document.getElementById('category-fields'), '<div class="repeat-row"><input data-category type="text" placeholder="Category"><input data-category-amount type="number" min="0" placeholder="Amount"><button type="button" class="remove-row" aria-label="Remove category">×</button></div>');
  });

  document.querySelector('[data-add-transaction]')?.addEventListener('click', () => {
    addRepeatRow(document.getElementById('transaction-fields'), '<div class="repeat-row transaction-input-row"><input data-merchant type="text" placeholder="Merchant"><input data-transaction-amount type="number" min="0" placeholder="$"><input data-transaction-category type="text" placeholder="Category"><button type="button" class="remove-row" aria-label="Remove transaction">×</button></div>');
  });

  form.addEventListener('click', (event) => {
    if (event.target.classList.contains('remove-row')) {
      const row = event.target.closest('.repeat-row');
      if (row && row.parentElement.children.length > 1) row.remove();
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    loading.classList.remove('hidden');
    resultBox.textContent = 'Reading your money story...';

    const categories = {};
    document.querySelectorAll('#category-fields .repeat-row').forEach((row) => {
      const name = row.querySelector('[data-category]').value.trim();
      const amount = Number(row.querySelector('[data-category-amount]').value || 0);
      if (name) categories[name] = amount;
    });

    const recentTransactions = [];
    document.querySelectorAll('#transaction-fields .repeat-row').forEach((row) => {
      const merchant = row.querySelector('[data-merchant]').value.trim();
      const amount = Number(row.querySelector('[data-transaction-amount]').value || 0);
      const category = row.querySelector('[data-transaction-category]').value.trim();
      if (merchant) recentTransactions.push({ merchant, amount, category });
    });

    try {
      const response = await fetch('/api/insight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_input: document.getElementById('user_input').value,
          monthly_income: Number(document.getElementById('monthly_income').value || 0),
          categories,
          recent_transactions: recentTransactions,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to generate an insight.');
      resultBox.textContent = data.insight;
    } catch (error) {
      resultBox.textContent = error.message || 'Something went wrong while generating your insight.';
    } finally {
      loading.classList.add('hidden');
    }
  });
}

document.querySelector('[data-read-notifications]')?.addEventListener('click', async (event) => {
  event.preventDefault();
  const token = document.querySelector('input[name="csrf_token"]')?.value;
  const response = await fetch('/notifications/read', { method: 'POST', headers: { 'X-CSRFToken': token || '' } });
  if (response.ok) window.location.reload();
});
