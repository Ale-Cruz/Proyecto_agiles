(() => {
  const app = document.getElementById('pos-app');
  if (!app?.posContext) return;
  const {api, cents, dollars, feedback, blocked, setPickupPending, showInvoice} = app.posContext;
  const el = id => document.getElementById(id);
  const dialog = el('pickup-dialog');
  const form = el('pickup-form');
  const storageKey = `cafeteria.pos.pickup.${app.dataset.usuario}.${app.dataset.apertura}`;
  const state = {summary:null, pending:null, busy:false, loading:false, uncertain:false, invalid:false};

  function error(message = '') {
    const box = dialog.querySelector('.pos-dialog-error');
    box.textContent = message;
    box.hidden = !message;
  }
  function refresh() { window.htmx?.trigger(document.body, 'pickupRefresh'); }
  function tab(name) {
    if (blocked() || state.loading || state.busy || state.pending || dialog.open) return false;
    const orders = name === 'pedidos';
    for (const [id, selected] of [['pos-tab-sale', !orders], ['pos-tab-orders', orders]]) {
      el(id).classList.toggle('active', selected);
      el(id).setAttribute('aria-selected', String(selected));
      el(id).tabIndex = selected ? 0 : -1;
    }
    el('pos-sale-pane').hidden = orders;
    el('pos-orders-pane').hidden = !orders;
    const url = new URL(location.href);
    if (orders) url.searchParams.set('tab', 'pedidos'); else url.searchParams.delete('tab');
    history.replaceState(null, '', url.href);
    if (orders) refresh();
    return true;
  }
  for (const [id, name] of [['pos-tab-sale', 'venta'], ['pos-tab-orders', 'pedidos']]) {
    el(id).addEventListener('click', () => tab(name));
    el(id).addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'venta' : event.key === 'End' ? 'pedidos' : name === 'venta' ? 'pedidos' : 'venta';
      if (tab(next)) el(next === 'pedidos' ? 'pos-tab-orders' : 'pos-tab-sale').focus();
    });
  }
  function persist() {
    try {
      if (state.pending) sessionStorage.setItem(storageKey, JSON.stringify({payload:state.pending, summary:state.summary}));
      else sessionStorage.removeItem(storageKey);
    } catch { /* El identificador también protege los reintentos de esta pestaña en el servidor. */ }
    setPickupPending(Boolean(state.pending));
  }
  function controls() {
    const locked = state.busy || Boolean(state.pending);
    const charge = el('pickup-action').value === 'cobrar';
    el('pickup-payment').hidden = !charge;
    el('pickup-cancellation').hidden = charge;
    el('pickup-action').disabled = locked;
    el('pickup-cash').disabled = locked || !charge;
    el('pickup-cash').required = charge;
    el('pickup-reason').disabled = locked || charge;
    el('pickup-reason').required = !charge;
    dialog.querySelectorAll('[data-pickup-close]').forEach(button => { button.disabled = locked; });
    const paid = cents(el('pickup-cash').value);
    const total = cents(state.summary?.total);
    const change = paid === null || total === null ? null : paid-total;
    el('pickup-change-box').classList.toggle('is-insufficient', change !== null && change < 0);
    el('pickup-change-box').classList.toggle('is-enough', change !== null && change >= 0);
    el('pickup-change-label').textContent = change === null ? 'Cambio' : change < 0 ? 'Efectivo insuficiente' : change === 0 ? 'Pago exacto' : 'Cambio';
    el('pickup-change').textContent = change === null ? '—' : change < 0 ? 'Faltan ' + dollars(-change) : dollars(change);
    el('pickup-submit').textContent = state.busy ? 'Procesando…' : state.uncertain ? 'Comprobar operación' : charge ? 'Efectuar cobro' : 'Anular pedido';
    el('pickup-submit').disabled = state.busy || state.invalid || (!state.pending && (charge ? !state.summary?.cobrable || change === null || change < 0 : !el('pickup-reason').value.trim()));
  }
  function render() {
    const summary = state.summary;
    el('pickup-title').textContent = summary.numero;
    el('pickup-student').textContent = summary.estudiante;
    el('pickup-items').replaceChildren();
    for (const item of summary.items) {
      const row = document.createElement('tr');
      for (const text of [item.nombre, String(item.cantidad), '$' + item.precio, '$' + item.importe]) {
        const cell = document.createElement('td');
        cell.textContent = text;
        row.append(cell);
      }
      el('pickup-items').append(row);
    }
    for (const field of ['subtotal', 'iva', 'total']) el('pickup-' + field).textContent = '$' + summary[field];
    el('pickup-action').value = state.pending?.accion || 'cobrar';
    el('pickup-cash').value = state.pending?.efectivo || '';
    el('pickup-reason').value = state.pending?.motivo || '';
    controls();
    if (!dialog.open) dialog.showModal();
    if (!state.pending) el('pickup-cash').focus();
  }
  app.addEventListener('click', async event => {
    const button = event.target.closest('[data-pickup-url]');
    if (!button || blocked() || state.loading || state.pending || dialog.open) return;
    state.loading = true;
    setPickupPending(true);
    button.disabled = true;
    try {
      state.summary = await api(button.dataset.pickupUrl, {apertura:Number(app.dataset.apertura)});
      state.invalid = state.uncertain = false;
      error(state.summary.advertencia);
      render();
    } catch (failure) { feedback(failure.message, true); refresh(); }
    finally { state.loading = false; button.disabled = false; setPickupPending(Boolean(state.pending)); }
  });
  function close() {
    if (state.busy || state.pending) return;
    dialog.close();
    refresh();
  }
  dialog.querySelectorAll('[data-pickup-close]').forEach(button => button.addEventListener('click', close));
  dialog.addEventListener('cancel', event => { if (state.busy || state.pending) event.preventDefault(); });
  dialog.addEventListener('close', refresh);
  for (const id of ['pickup-cash', 'pickup-reason']) el(id).addEventListener('input', controls);
  el('pickup-action').addEventListener('change', controls);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.busy || state.invalid || el('pickup-submit').disabled) return;
    if (!state.pending) {
      const charge = el('pickup-action').value === 'cobrar';
      state.pending = {cotizacion:state.summary.cotizacion, accion:charge ? 'cobrar' : 'anular', operacion_id:crypto.randomUUID(),
        ...(charge ? {efectivo:(cents(el('pickup-cash').value)/100).toFixed(2)} : {motivo:el('pickup-reason').value.trim()})};
      persist();
    }
    state.busy = true;
    controls();
    error();
    try {
      const result = await api(app.dataset.atenderPedido, state.pending);
      state.pending = null;
      state.uncertain = false;
      persist();
      dialog.close();
      feedback(result.accion === 'cobrar' ? `Pedido ${result.numero} cobrado. Cambio: $${result.cambio}.` : `Pedido ${result.numero} anulado.`);
      if (result.accion === 'cobrar') void showInvoice(result.factura_url);
    } catch (failure) {
      state.uncertain = Boolean(failure.uncertain);
      if (state.uncertain) error('No se pudo comprobar el resultado. Pulsa «Comprobar operación» para verificar la misma operación.');
      else {
        state.pending = null;
        state.invalid = true;
        persist();
        error(failure.message);
      }
    } finally {
      state.busy = false;
      controls();
      if (!dialog.open) refresh();
    }
  });
  document.body.addEventListener('htmx:beforeRequest', event => {
    if (!['pickup-board', 'pickup-search'].includes(event.detail.elt?.id)) return;
    if (el('pos-orders-pane').hidden || blocked() || state.loading || state.busy || dialog.open ||
        (event.detail.elt.id === 'pickup-board' && el('pickup-board')?.contains(document.activeElement))) event.preventDefault();
  });
  for (const type of ['htmx:sendError', 'htmx:responseError', 'htmx:timeout', 'htmx:afterRequest']) {
    document.body.addEventListener(type, event => {
      if (event.detail.target?.id === 'pickup-board') el('pickup-network-error').hidden = type === 'htmx:afterRequest' && event.detail.successful;
    });
  }
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); } catch { /* Borrador inválido. */ }
  function restore() {
    if (!saved?.payload?.operacion_id || !Array.isArray(saved.summary?.items) || blocked()) return;
    tab('pedidos');
    state.pending = saved.payload;
    state.summary = saved.summary;
    state.uncertain = true;
    setPickupPending(true);
    error('Hay una operación pendiente de comprobar. Verifícala antes de continuar.');
    render();
    saved = null;
  }
  if (new URL(location.href).searchParams.get('tab') === 'pedidos') tab('pedidos');
  // Los scripts diferidos corren antes de que HTMX termine de procesar el HTML.
  if (document.readyState !== 'complete') document.addEventListener('DOMContentLoaded', () => {
    if (!el('pos-orders-pane').hidden && !dialog.open) refresh();
  }, {once:true});
  restore();
  el('pos-confirm').addEventListener('close', () => { setTimeout(restore, 0); });
})();
