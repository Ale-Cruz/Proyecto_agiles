(() => {
  const csrf = () => document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  const cents = value => {
    if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(String(value))) return null;
    const [whole, fraction = ''] = String(value).split('.');
    return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  };
  const dollars = value => '$' + (value / 100).toFixed(2);
  function dialogError(dialog, message = '') {
    const target = dialog.querySelector('.pos-dialog-error');
    target.textContent = message;
    target.hidden = !message;
  }
  async function api(url, data, signal) {
    let response;
    try {
      response = await fetch(url, {
        method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', signal,
        headers: {'Accept':'application/json', 'HX-Request':'true', ...(data === undefined ? {} : {'Content-Type':'application/json', 'X-CSRFToken':csrf()})},
        ...(data === undefined ? {} : {body:JSON.stringify(data)}),
      });
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      const failure = new Error('No se pudo conectar con el servidor. Intenta de nuevo.');
      failure.uncertain = true;
      throw failure;
    }
    const redirect = response.headers.get('HX-Redirect');
    if (redirect) {
      const url = new URL(redirect, location.origin);
      url.searchParams.set('next', location.pathname);
      location.assign(url.href);
      const error = new Error('Inicia sesión para continuar.');
      error.uncertain = true;
      throw error;
    }
    let result;
    try { result = await response.json(); }
    catch {
      const error = new Error('No se pudo comprobar el resultado. Intenta de nuevo.');
      error.uncertain = true;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(result.error || 'No se pudo completar la operación.');
      error.status = response.status;
      error.resumen = result.resumen;
      error.uncertain = response.status >= 500;
      throw error;
    }
    return result;
  }

  const opening = document.getElementById('pos-opening');
  if (opening) {
    const form = document.getElementById('pos-opening-form');
    document.querySelector('[data-pos-open]')?.addEventListener('click', () => opening.showModal());
    opening.addEventListener('cancel', event => {
      if (form.dataset.busy) event.preventDefault();
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (form.dataset.busy) return;
      form.dataset.busy = 'true';
      form.querySelector('button[type="submit"]').disabled = true;
      dialogError(opening);
      try {
        const result = await api(form.dataset.url, {monto:form.elements.monto.value, token:form.elements.token.value});
        location.assign(result.redirect);
      } catch (error) { dialogError(opening, error.message); }
      finally {
        delete form.dataset.busy;
        form.querySelector('button[type="submit"]').disabled = false;
      }
    });
    opening.showModal();
  }

  const app = document.getElementById('pos-app');
  if (!app) return;
  const el = id => document.getElementById(id);
  const state = {items:[], subtotal:'0.00', iva:'0.00', total:'0.00', quote:null,
    operation:crypto.randomUUID(), busy:false, submitting:false, uncertain:false,
    pending:null, invalid:false, closingBusy:false, authorization:null, expected:null};
  const storageKey = `cafeteria.pos.pending.${app.dataset.usuario}.${app.dataset.apertura}`;
  const search = el('pos-search');
  const results = el('pos-search-results');
  const confirm = el('pos-confirm');
  const closing = el('pos-closing');
  const invoice = el('pos-invoice');
  let invoiceUrl, invoiceSequence = 0;
  let searchTimer, searchAbort, searchSequence = 0, found = [];

  function feedback(message = '', error = false) {
    const box = el('pos-feedback');
    box.textContent = message;
    box.hidden = !message;
    box.classList.toggle('is-error', error);
    box.setAttribute('role', error ? 'alert' : 'status');
  }
  async function showInvoice(url) {
    if (!url) return;
    const sequence = ++invoiceSequence;
    // La factura se carga después del cobro; un fallo aquí nunca repite la venta.
    try {
      const target = new URL(url, location.origin);
      if (target.origin !== location.origin) return;
      invoiceUrl = target;
      const printUrl = new URL(target);
      printUrl.searchParams.set('imprimir', '1');
      el('pos-invoice-print').href = printUrl.href;
      el('pos-invoice-error').hidden = true;
      el('pos-invoice-retry').hidden = true;
      const loading = document.createElement('p');
      loading.className = 'invoice-loading';
      loading.textContent = 'Cargando factura…';
      el('pos-invoice-content').replaceChildren(loading);
      if (!invoice.open) invoice.showModal();
      updateControls();
      const dataUrl = new URL(target);
      dataUrl.searchParams.set('formato', 'json');
      const result = await api(dataUrl.href);
      if (sequence !== invoiceSequence) return;
      if (typeof result.html !== 'string') throw new Error('Factura no disponible.');
      // HTML generado por Django, con los datos escapados en la plantilla.
      el('pos-invoice-content').innerHTML = result.html;
    } catch {
      if (sequence !== invoiceSequence) return;
      el('pos-invoice-content').replaceChildren();
      el('pos-invoice-error').textContent = 'El cobro ya está registrado. No se pudo cargar la factura; puedes reintentar o abrirla con «Imprimir».';
      el('pos-invoice-error').hidden = false;
      el('pos-invoice-retry').hidden = false;
    }
  }
  invoice.querySelectorAll('[data-invoice-close]').forEach(button => button.addEventListener('click', () => invoice.close()));
  el('pos-invoice-retry').addEventListener('click', () => showInvoice(invoiceUrl?.href));
  invoice.addEventListener('close', () => {
    invoiceSequence++;
    updateControls();
    window.htmx?.trigger(document.body, 'pickupRefresh');
  });
  function persistPending() {
    try {
      if (state.pending) sessionStorage.setItem(storageKey, JSON.stringify({payload:state.pending, items:state.items,
        subtotal:state.subtotal, iva:state.iva, total:state.total}));
      else sessionStorage.removeItem(storageKey);
    } catch { /* El servidor también identifica los reintentos de la misma operación. */ }
  }
  function updatePayment() {
    const paid = cents(el('pos-cash').value);
    const total = cents(state.total);
    const change = paid === null || !state.items.length ? null : paid - total;
    const box = el('pos-change-box');
    box.classList.toggle('is-insufficient', change !== null && change < 0);
    box.classList.toggle('is-enough', change !== null && change >= 0);
    el('pos-change-label').textContent = change === null ? 'Cambio' : change < 0 ? 'Efectivo insuficiente' : change === 0 ? 'Pago exacto' : 'Cambio';
    el('pos-change').textContent = change === null ? '—' : change < 0 ? 'Faltan ' + dollars(-change) : dollars(change);
    el('pos-checkout').disabled = state.busy || Boolean(state.pending) || invoice.open || app.dataset.pickupPending === 'true' || !state.quote || change === null || change < 0;
  }
  function updateControls() {
    const disabled = state.busy || Boolean(state.pending) || invoice.open || app.dataset.pickupPending === 'true';
    app.querySelectorAll('#pos-items button, #pos-items input, #pos-search-results button').forEach(button => {
      button.disabled = disabled || button.dataset.soldout === 'true';
    });
    search.disabled = disabled;
    el('pos-cash').disabled = disabled;
    el('pos-close-open').disabled = disabled;
    updatePayment();
  }
  function renderItems() {
    const body = el('pos-items');
    body.replaceChildren();
    for (const item of state.items) {
      const row = document.createElement('tr');
      row.innerHTML = '<td><strong></strong><small></small></td><td><div class="pos-quantity"><button type="button" data-delta="-1" aria-label="Restar una unidad">−</button><input type="number" min="1" step="1"><button type="button" data-delta="1" aria-label="Añadir una unidad">+</button></div></td><td></td><td></td><td><button type="button" class="pos-remove" aria-label="Quitar producto">×</button></td>';
      row.dataset.id = item.id;
      row.querySelector('strong').textContent = item.nombre;
      row.querySelector('small').textContent = item.codigo;
      const quantity = row.querySelector('input');
      quantity.value = item.cantidad;
      quantity.max = item.disponible;
      quantity.setAttribute('aria-label', 'Cantidad de ' + item.nombre);
      row.children[2].textContent = '$' + item.precio;
      row.children[3].textContent = '$' + item.importe;
      body.append(row);
    }
    el('pos-empty').hidden = Boolean(state.items.length);
    el('pos-subtotal').textContent = '$' + state.subtotal;
    el('pos-iva').textContent = '$' + state.iva;
    el('pos-total').textContent = '$' + state.total;
    updateControls();
  }
  function renderSearch() {
    results.replaceChildren();
    if (!found.length) {
      const empty = document.createElement('div');
      empty.className = 'pos-search-empty';
      empty.textContent = 'No hay productos que coincidan.';
      results.append(empty);
    }
    for (const product of found) {
      const row = document.createElement('div');
      row.className = 'pos-product-result';
      row.innerHTML = '<div><strong></strong><small></small></div><div class="pos-result-action"><span class="pos-result-price"></span><button class="pos-add" type="button">Agregar</button></div>';
      row.querySelector('strong').textContent = product.nombre;
      row.querySelector('small').textContent = product.codigo + ' · ' + (product.disponible ? product.disponible + ' disponibles' : 'Agotado');
      row.querySelector('.pos-result-price').textContent = '$' + product.precio;
      const button = row.querySelector('button');
      button.dataset.add = product.id;
      button.dataset.soldout = String(product.disponible <= (state.items.find(item => item.id === product.id)?.cantidad || 0));
      button.disabled = button.dataset.soldout === 'true' || state.busy || Boolean(state.pending);
      results.append(row);
    }
    results.hidden = false;
  }
  async function searchProducts() {
    searchAbort?.abort();
    searchAbort = new AbortController();
    const sequence = ++searchSequence;
    try {
      const url = new URL(app.dataset.productos, location.origin);
      url.searchParams.set('q', search.value);
      url.searchParams.set('apertura', app.dataset.apertura);
      const data = await api(url.href, undefined, searchAbort.signal);
      if (sequence !== searchSequence) return;
      found = data.productos;
      if (document.activeElement === search || results.contains(document.activeElement)) renderSearch();
    } catch (error) { if (error.name !== 'AbortError') feedback(error.message, true); }
  }
  async function setCart(next) {
    if (state.busy || state.pending || invoice.open || app.dataset.pickupPending === 'true') return false;
    feedback();
    if (!next.length) {
      Object.assign(state, {items:[], subtotal:'0.00', iva:'0.00', total:'0.00', quote:null});
      renderItems();
      return true;
    }
    state.busy = true;
    updateControls();
    let success = false;
    try {
      const data = await api(app.dataset.cotizar, {apertura:Number(app.dataset.apertura), items:next.map(item => ({id:item.id,cantidad:item.cantidad}))});
      state.items = next.map(item => data.items.find(line => line.id === item.id));
      Object.assign(state, {subtotal:data.subtotal, iva:data.iva, total:data.total, quote:data.cotizacion});
      success = true;
    } catch (error) { state.quote = null; feedback(error.message, true); }
    finally { state.busy = false; renderItems(); }
    return success;
  }
  search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(searchProducts, 220); });
  search.addEventListener('focus', searchProducts);
  search.addEventListener('keydown', event => { if (event.key === 'Escape') results.hidden = true; });
  document.addEventListener('click', event => { if (!event.target.closest('.pos-search-area')) results.hidden = true; });
  results.addEventListener('click', async event => {
    const button = event.target.closest('[data-add]');
    if (!button) return;
    const id = Number(button.dataset.add);
    const next = state.items.map(item => ({...item}));
    const existing = next.find(item => item.id === id);
    if (existing) existing.cantidad++; else next.push({id,cantidad:1});
    await setCart(next);
    search.focus();
    search.select();
  });
  el('pos-items').addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    const id = Number(button.closest('tr').dataset.id);
    let next = state.items.map(item => ({...item}));
    if (button.classList.contains('pos-remove')) next = next.filter(item => item.id !== id);
    else {
      const item = next.find(line => line.id === id);
      item.cantidad += Number(button.dataset.delta);
      if (item.cantidad < 1) return;
    }
    await setCart(next);
  });
  el('pos-items').addEventListener('change', async event => {
    if (!event.target.matches('input')) return;
    const quantity = Number(event.target.value);
    if (!Number.isInteger(quantity) || quantity < 1) { renderItems(); return; }
    const id = Number(event.target.closest('tr').dataset.id);
    await setCart(state.items.map(item => ({...item,cantidad:item.id === id ? quantity : item.cantidad})));
  });
  el('pos-cash').addEventListener('input', updatePayment);

  function confirmControls() {
    el('pos-finish').disabled = state.submitting || state.invalid;
    el('pos-continue').disabled = state.submitting || state.uncertain;
    el('pos-finish').textContent = state.submitting ? 'Procesando…' : state.uncertain ? 'Comprobar venta' : 'Sí, terminar';
  }
  function showConfirmation() {
    const paid = state.pending ? cents(state.pending.efectivo) : cents(el('pos-cash').value);
    el('confirm-total').textContent = '$' + state.total;
    el('confirm-cash').textContent = dollars(paid);
    el('confirm-change').textContent = dollars(paid-cents(state.total));
    confirmControls();
    if (!confirm.open) confirm.showModal();
  }
  el('pos-checkout').addEventListener('click', async () => {
    if (!await setCart(state.items)) return;
    const paid = cents(el('pos-cash').value);
    if (paid === null || paid < cents(state.total)) { feedback('Revisa el efectivo recibido.', true); return; }
    state.invalid = false;
    dialogError(confirm);
    results.hidden = true;
    showConfirmation();
  });
  confirm.addEventListener('cancel', event => { if (state.submitting || state.uncertain) event.preventDefault(); });
  el('pos-continue').addEventListener('click', () => { if (!state.submitting && !state.uncertain) confirm.close(); });
  el('pos-finish').addEventListener('click', async () => {
    if (state.submitting || state.invalid) return;
    if (!state.pending) {
      state.pending = {cotizacion:state.quote, efectivo:(cents(el('pos-cash').value)/100).toFixed(2), operacion_id:state.operation};
      persistPending();
    }
    state.submitting = true;
    confirmControls();
    updateControls();
    dialogError(confirm);
    try {
      const data = await api(app.dataset.cobrar, state.pending);
      Object.assign(state, {pending:null,uncertain:false,items:[],quote:null,subtotal:'0.00',iva:'0.00',total:'0.00',operation:crypto.randomUUID()});
      persistPending();
      el('pos-cash').value = '';
      confirm.close();
      feedback(`Venta ${data.numero} registrada. Cambio: $${data.cambio}.`);
      found = [];
      results.hidden = true;
      void showInvoice(data.factura_url);
    } catch (error) {
      state.uncertain = Boolean(error.uncertain);
      if (state.uncertain) dialogError(confirm, 'No se pudo comprobar el resultado. Pulsa «Comprobar venta» para verificar la misma operación.');
      else {
        Object.assign(state, {pending:null,invalid:true,quote:null});
        persistPending();
        dialogError(confirm, error.message);
      }
    } finally {
      state.submitting = false;
      confirmControls();
      renderItems();
    }
  });

  function closingButtons(disabled) {
    closing.querySelectorAll('button,input').forEach(control => { control.disabled = disabled; });
  }
  function closingSummary(summary) {
    state.expected = summary.esperado;
    el('closing-initial').textContent = '$' + summary.monto_inicial;
    el('closing-sales').textContent = '$' + summary.ventas;
    el('closing-expected').textContent = '$' + summary.esperado;
    el('closing-other').textContent = '$' + summary.otros;
    el('closing-other-row').hidden = Number(summary.otros) === 0;
    updateDifference();
  }
  function updateDifference() {
    const counted = cents(el('closing-counted').value);
    const diff = counted === null ? null : counted-cents(state.expected);
    el('closing-difference').textContent = diff === null ? '—' : (diff < 0 ? '−' : diff > 0 ? '+' : '') + dollars(Math.abs(diff));
    el('closing-difference-box').classList.toggle('is-insufficient', diff !== null && diff < 0);
    el('closing-difference-box').classList.toggle('is-enough', diff !== null && diff >= 0);
  }
  el('pos-close-open').addEventListener('click', () => {
    if (state.busy || state.pending || state.items.length || invoice.open || app.dataset.pickupPending === 'true') { feedback('Termina o vacía la venta y comprueba los cobros pendientes antes de cerrar caja.', true); return; }
    state.authorization = null;
    el('pos-credentials').reset();
    el('pos-credentials').hidden = false;
    el('pos-counting').hidden = true;
    el('closing-counted').value = '';
    dialogError(closing);
    closing.showModal();
    el('closing-password').focus();
  });
  closing.addEventListener('cancel', event => { if (state.closingBusy) event.preventDefault(); });
  closing.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => { if (!state.closingBusy) closing.close(); }));
  closing.addEventListener('close', () => { el('closing-password').value = ''; state.authorization = null; });
  el('pos-credentials').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.closingBusy) return;
    const payload = {apertura:Number(app.dataset.apertura), usuario:el('closing-user').value, password:el('closing-password').value};
    el('closing-password').value = '';
    state.closingBusy = true;
    closingButtons(true);
    dialogError(closing);
    try {
      const data = await api(app.dataset.verificar, payload);
      state.authorization = data.autorizacion;
      closingSummary(data.resumen);
      el('pos-credentials').hidden = true;
      el('pos-counting').hidden = false;
    } catch (error) { dialogError(closing,error.message); }
    finally {
      payload.password = '';
      state.closingBusy = false;
      closingButtons(false);
      (state.authorization ? el('closing-counted') : el('closing-password')).focus();
    }
  });
  el('closing-counted').addEventListener('input', updateDifference);
  el('pos-counting').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.closingBusy) return;
    state.closingBusy = true;
    closingButtons(true);
    dialogError(closing);
    try {
      const data = await api(app.dataset.cerrar, {autorizacion:state.authorization, esperado:state.expected, contado:el('closing-counted').value});
      location.assign(data.redirect);
    } catch (error) {
      if (error.resumen) closingSummary(error.resumen);
      else if (error.status === 403 || error.message.includes('credenciales')) {
        state.authorization = null;
        el('pos-counting').hidden = true;
        el('pos-credentials').hidden = false;
      }
      dialogError(closing,error.message);
    } finally { state.closingBusy = false; closingButtons(false); }
  });

  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (saved?.payload?.operacion_id && Array.isArray(saved.items)) {
      Object.assign(state, {pending:saved.payload,items:saved.items,subtotal:saved.subtotal,iva:saved.iva,total:saved.total,uncertain:true});
      el('pos-cash').value = saved.payload.efectivo;
      dialogError(confirm,'Hay una operación pendiente de comprobar. Verifícala antes de continuar vendiendo.');
      showConfirmation();
    }
  } catch { /* Un borrador local inválido no se envía al servidor. */ }
  renderItems();
  app.posContext = {
    api, cents, dollars, feedback, showInvoice,
    blocked: () => state.busy || Boolean(state.pending) || state.closingBusy || confirm.open || closing.open || invoice.open,
    setPickupPending(value) { app.dataset.pickupPending = String(value); updateControls(); },
  };
})();
