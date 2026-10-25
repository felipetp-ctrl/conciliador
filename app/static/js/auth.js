/* conciliador · telas de autenticação. JS mínimo, sem dependências.
   Delegação de eventos no document: continua funcionando depois dos swaps do HTMX (hx-boost). */
(function () {
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-toggle-password]");
    if (!btn) return;
    var input = document.getElementById(btn.getAttribute("aria-controls"));
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-pressed", show ? "true" : "false");
    btn.setAttribute("aria-label", show ? "Ocultar senha" : "Mostrar senha");
    var icons = btn.querySelectorAll("svg");
    if (icons.length === 2) {
      icons[0].hidden = show;
      icons[1].hidden = !show;
    }
  });

  // Após um swap do HTMX (ex.: erro de login), devolve o foco ao primeiro campo marcado com autofocus.
  document.addEventListener("htmx:afterSettle", function () {
    var el = document.querySelector(".auth-form [autofocus]");
    if (el) el.focus();
  });
})();
