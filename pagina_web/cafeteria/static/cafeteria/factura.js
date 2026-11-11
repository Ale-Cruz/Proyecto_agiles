(() => {
  document.querySelector('[data-print-invoice]')?.addEventListener('click', () => window.print());
  if (new URL(location.href).searchParams.get('imprimir') === '1') {
    window.addEventListener('load', () => window.print(), {once:true});
  }
})();
