(() => {
  const form = document.getElementById('schedule-form');
  if (!form) return;
  const enabled = document.getElementById('schedule-enabled');
  const fields = document.getElementById('schedule-fields');
  const submit = document.getElementById('schedule-submit');
  function update() {
    fields.disabled = !enabled.checked;
    fields.querySelectorAll('input').forEach(input => { input.required = enabled.checked; });
    submit.disabled = !enabled.checked && form.dataset.initialEnabled !== 'true';
    submit.textContent = enabled.checked ? 'Aplicar horario' : form.dataset.initialEnabled === 'true' ? 'Desactivar horario' : 'Aplicar horario';
  }
  enabled.addEventListener('change', update);
  form.addEventListener('submit', () => { submit.disabled = true; });
  update();
})();
