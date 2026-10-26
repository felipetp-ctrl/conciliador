// conciliador · comportamento mínimo do design system (sem framework). Carregar com defer.
// 1) Dropzone: arrastar-e-soltar envia o <form> via HTMX.  2) Linhas de tabela clicáveis.  3) Setas nas abas.
(function () {
  function bindDropzones(root) {
    root.querySelectorAll('.dropzone[data-dropzone]').forEach(function (dz) {
      if (dz.__bound) return; dz.__bound = true;
      var input = dz.querySelector('input[type=file]'); if (!input) return;
      ['dragenter', 'dragover'].forEach(function (e) { dz.addEventListener(e, function (ev) { ev.preventDefault(); dz.classList.add('is-dragover'); }); });
      ['dragleave', 'drop'].forEach(function (e) { dz.addEventListener(e, function () { dz.classList.remove('is-dragover'); }); });
      dz.addEventListener('drop', function (ev) { ev.preventDefault(); input.files = ev.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles: true })); });
    });
  }
  function bindRows(root) {
    root.querySelectorAll('tr[data-href]').forEach(function (tr) {
      if (tr.__bound) return; tr.__bound = true;
      tr.addEventListener('click', function (ev) { if (ev.target.closest('a,button,input,select')) return; window.location = tr.dataset.href; });
    });
  }
  function bindTabs(root) {
    root.querySelectorAll('[role=tablist]').forEach(function (tl) {
      if (tl.__bound) return; tl.__bound = true;
      tl.addEventListener('keydown', function (ev) {
        if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
        var tabs = Array.prototype.slice.call(tl.querySelectorAll('[role=tab]')); var i = tabs.indexOf(document.activeElement); if (i < 0) return;
        var n = tabs[(i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]; n.focus(); ev.preventDefault();
      });
    });
  }
  function init(root) { bindDropzones(root); bindRows(root); bindTabs(root); }
  document.addEventListener('DOMContentLoaded', function () { init(document); });
  document.addEventListener('htmx:load', function (ev) { init(ev.target); });
  // Selects que enviam o formulário ao mudar (sem onchange inline, bloqueado pela CSP).
  document.addEventListener('change', function (ev) {
    var el = ev.target.closest('[data-auto-submit]');
    if (el && el.form) el.form.requestSubmit();
  });
})();
