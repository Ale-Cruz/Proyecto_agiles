// Delegar los eventos permite reutilizar los controles en formularios cargados por HTMX.
document.addEventListener('click', event => {
  const button = event.target.closest('.password-toggle');
  if (!button) return;
  const field = document.getElementById(button.getAttribute('aria-controls'));
  if (!field) return;
  const show = field.type === 'password';
  field.type = show ? 'text' : 'password';
  button.textContent = show ? 'Ocultar' : 'Mostrar';
  button.setAttribute('aria-pressed', String(show));
});

// Los selects nuevos siguen funcionando tras reemplazar el listado; buscar se envia al confirmar.
document.addEventListener('change', event => {
  if (event.target.matches('.employee-filters select')) {
    event.target.form?.dispatchEvent(new Event('filtrosCambiados', {bubbles: true}));
  }
});

const menuButton = document.querySelector('.menu-toggle');
function setMenu(open) {
  document.body.classList.toggle('sidebar-open', open);
  menuButton?.setAttribute('aria-expanded', String(open));
  menuButton?.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
  if (!open) menuButton?.focus();
}
menuButton?.addEventListener('click', () => setMenu(!document.body.classList.contains('sidebar-open')));
document.querySelector('.sidebar-overlay')?.addEventListener('click', () => setMenu(false));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) setMenu(false);
});

const employeeModal = document.getElementById('employee-modal');
if (employeeModal) {
  let modalOpener = null;
  let openerHref = '';
  let focusAfterRefresh = false;
  const modalContent = document.getElementById('employee-modal-content');
  const isSaving = () => Boolean(employeeModal.querySelector('form.htmx-request'));

  function restoreOpenerFocus() {
    const replacement = [...document.querySelectorAll('[data-employee-form-link]')]
      .find(link => link.href === openerHref);
    const target = modalOpener?.isConnected ? modalOpener : replacement;
    (target || document.querySelector('[data-employee-form-link]'))?.focus({preventScroll: true});
  }

  function feedback(message, error = false) {
    const target = document.getElementById(employeeModal.open ? 'employee-modal-feedback' : 'employee-feedback');
    target.textContent = message;
    target.hidden = false;
    target.classList.toggle('feedback-error', error);
    target.setAttribute('role', error ? 'alert' : 'status');
  }

  function closeModal(force = false) {
    if (!force && isSaving()) return;
    employeeModal.close();
  }

  employeeModal.addEventListener('cancel', event => {
    if (isSaving()) event.preventDefault();
  });
  employeeModal.addEventListener('close', () => {
    document.body.classList.remove('employee-modal-open');
    modalContent.replaceChildren();
    document.getElementById('employee-modal-feedback').hidden = true;
    restoreOpenerFocus();
  });
  employeeModal.addEventListener('click', event => {
    if (event.target.closest('[data-modal-close]')) closeModal();
    if (event.target === employeeModal) {
      const bounds = employeeModal.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) closeModal();
    }
  });

  document.body.addEventListener('htmx:beforeRequest', event => {
    const opener = event.detail.elt.closest('[data-employee-form-link]');
    if (opener) {
      modalOpener = opener;
      openerHref = opener.href;
      document.getElementById('employee-feedback').hidden = true;
    }
    if (event.detail.target?.id === 'employee-list') {
      document.getElementById('employee-list').setAttribute('aria-busy', 'true');
    }
  });

  document.body.addEventListener('htmx:afterSwap', event => {
    if (event.detail.target?.id === 'employee-modal-content') {
      document.getElementById('employee-modal-feedback').hidden = true;
      if (!employeeModal.open) employeeModal.showModal();
      document.body.classList.add('employee-modal-open');
      const field = modalContent.querySelector('[aria-invalid="true"], .form-alert') ||
        modalContent.querySelector('[autofocus]');
      if (field?.classList.contains('form-alert')) field.setAttribute('tabindex', '-1');
      field?.focus();
    }
    if (event.detail.target?.id === 'employee-list' && focusAfterRefresh) {
      restoreOpenerFocus();
      focusAfterRefresh = false;
    }
  });

  document.body.addEventListener('empleadoGuardado', event => {
    focusAfterRefresh = true;
    closeModal(true);
    feedback(event.detail.mensaje);
    if (typeof event.detail.nombreActual === 'string') {
      document.querySelectorAll('[data-current-user-name]').forEach(node => {
        node.textContent = event.detail.nombreActual;
      });
      document.querySelectorAll('[data-current-user-initial]').forEach(node => {
        node.textContent = event.detail.nombreActual.charAt(0).toUpperCase();
      });
    }
  });

  document.body.addEventListener('htmx:afterRequest', () => {
    document.getElementById('employee-list')?.removeAttribute('aria-busy');
  });

  document.body.addEventListener('htmx:responseError', event => {
    const status = event.detail.xhr.status;
    feedback(status === 403 ? 'Tu sesión ya no permite esta acción. Actualiza la página para continuar.' :
      status === 404 ? 'Este usuario ya no está disponible. Actualiza el listado.' :
      'No se pudo completar la operación. Inténtalo de nuevo.', true);
  });
  document.body.addEventListener('htmx:sendError', () => {
    feedback('No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.', true);
  });
}

const auditFeedback = document.getElementById('audit-feedback');
if (auditFeedback) {
  document.body.addEventListener('htmx:beforeRequest', event => {
    if (event.detail.target?.id !== 'audit-list') return;
    auditFeedback.hidden = true;
    document.getElementById('audit-list').setAttribute('aria-busy', 'true');
  });
  document.body.addEventListener('htmx:afterRequest', () => {
    document.getElementById('audit-list')?.removeAttribute('aria-busy');
  });
  function auditError(message) {
    auditFeedback.textContent = message;
    auditFeedback.hidden = false;
  }
  document.body.addEventListener('htmx:responseError', () => {
    auditError('No se pudo consultar el historial. Actualiza la página e inténtalo de nuevo.');
  });
  document.body.addEventListener('htmx:sendError', () => {
    auditError('No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.');
  });
}

const moduleModal = document.getElementById('module-modal');
if (moduleModal) {
  const content = document.getElementById('module-modal-content');
  const outsideFeedback = document.getElementById('module-feedback');
  const insideFeedback = document.getElementById('module-modal-feedback');
  let openerHref = '';
  let focusAfterRefresh = false;
  const saving = () => Boolean(moduleModal.querySelector('form.htmx-request'));
  function restoreFocus() {
    const links = [...document.querySelectorAll('[data-module-form-link]')];
    (links.find(link => link.href === openerHref) || links[0])?.focus({preventScroll:true});
  }
  function closeModule(force = false) {
    if (force || !saving()) moduleModal.close();
  }
  function moduleError(message) {
    const target = moduleModal.open ? insideFeedback : outsideFeedback;
    target.textContent = message;
    target.hidden = false;
    target.classList.add('feedback-error');
    target.setAttribute('role', 'alert');
  }
  moduleModal.addEventListener('cancel', event => {if (saving()) event.preventDefault();});
  moduleModal.addEventListener('close', () => {
    document.body.classList.remove('employee-modal-open');
    content.replaceChildren();
    insideFeedback.hidden = true;
    restoreFocus();
  });
  moduleModal.addEventListener('click', event => {
    if (event.target.closest('[data-module-close]')) closeModule();
    if (event.target === moduleModal) {
      const bounds = moduleModal.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeModule();
    }
  });
  document.body.addEventListener('htmx:beforeRequest', event => {
    const link = event.detail.elt.closest('[data-module-form-link]');
    if (link) {openerHref = link.href; outsideFeedback.hidden = true;}
    if (event.detail.target?.id === 'module-list') document.getElementById('module-list')?.setAttribute('aria-busy','true');
  });
  document.body.addEventListener('htmx:afterSwap', event => {
    if (event.detail.target?.id === 'module-modal-content') {
      insideFeedback.hidden = true;
      if (!moduleModal.open) moduleModal.showModal();
      document.body.classList.add('employee-modal-open');
      const field = content.querySelector('[aria-invalid="true"]') || content.querySelector('[autofocus]');
      field?.focus();
      content.querySelector('.form-alert')?.scrollIntoView({block:'nearest'});
    }
    if (event.detail.target?.id === 'module-list' && focusAfterRefresh) {restoreFocus(); focusAfterRefresh = false;}
  });
  document.body.addEventListener('catalogoGuardado', event => {
    focusAfterRefresh = true;
    closeModule(true);
    outsideFeedback.textContent = event.detail.mensaje;
    outsideFeedback.hidden = false;
    outsideFeedback.classList.remove('feedback-error');
    outsideFeedback.setAttribute('role','status');
  });
  document.body.addEventListener('htmx:afterRequest', () => document.getElementById('module-list')?.removeAttribute('aria-busy'));
  document.body.addEventListener('htmx:responseError', event => moduleError(event.detail.xhr.status === 403 ? 'Tu sesión ya no permite esta acción. Actualiza la página.' : 'No se pudo completar la operación. Inténtalo de nuevo.'));
  document.body.addEventListener('htmx:sendError', () => moduleError('No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'));
}


// Buscar otro producto invalida la seleccion anterior antes de enviar el formulario.
document.addEventListener('input', event => {
  if (!event.target.matches('[data-inventory-product-search]')) return;
  const picker = event.target.closest('#inventory-product-picker');
  const selected = picker?.querySelector('input[name="producto"]');
  if (!selected) return;
  selected.value = '';
  picker.querySelector('[data-stock-title]').textContent = 'Selecciona un producto para consultar su stock.';
  picker.querySelector('[data-stock-code]').textContent = '';
  picker.querySelector('[data-stock-count]').textContent = '';
  // Retirar resultados previos evita seleccionar coincidencias de otra consulta.
  picker.querySelector('#movement-product-results').replaceChildren();
});
document.body.addEventListener('htmx:afterSwap', event => {
  if (event.detail.target?.id !== 'stock-info') return;
  const picker = event.detail.target.closest('#inventory-product-picker');
  if (!picker) return;
  picker.querySelector('[data-inventory-product-search]').value = '';
  picker.querySelector('#movement-product-results').replaceChildren();
  picker.querySelector('[data-inventory-product-error]')?.setAttribute('hidden', '');
});
