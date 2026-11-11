// El sondeo espera mientras el usuario navega una comanda con el teclado.
document.body.addEventListener('htmx:beforeRequest', event => {
  if (event.detail.elt?.id === 'orders-board' &&
      event.detail.elt.contains(document.activeElement)) event.preventDefault();
});

function showOrderNetworkError(event) {
  if (event.detail.target?.id !== 'orders-board') return;
  const alert = document.getElementById('orders-network-error');
  if (alert) alert.hidden = false;
}
document.body.addEventListener('htmx:sendError', showOrderNetworkError);
document.body.addEventListener('htmx:responseError', showOrderNetworkError);
document.body.addEventListener('htmx:timeout', showOrderNetworkError);
document.body.addEventListener('htmx:afterRequest', event => {
  if (event.detail.target?.id === 'orders-board' && event.detail.successful) {
    const alert = document.getElementById('orders-network-error');
    if (alert) alert.hidden = true;
  }
});
