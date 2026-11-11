for (const type of ['htmx:sendError', 'htmx:responseError', 'htmx:timeout', 'htmx:afterRequest']) {
  document.body.addEventListener(type, event => {
    if (event.detail.target?.id !== 'report-list') return;
    const feedback = document.getElementById('report-feedback');
    if (feedback) feedback.hidden = type === 'htmx:afterRequest' && event.detail.successful;
  });
}
