// conciliador · motor de rolagem da landing, JavaScript puro (~100 linhas). Carregar com defer.
// Contratos no HTML:
//   [data-reveal]            entra uma vez ao aparecer (classe .is-in). Atraso: style="--d:120ms".
//   [data-scene]             seção alta com filho sticky; recebe a CSS var --p (0→1) durante a rolagem.
//   [data-scene="through"]   --p mede a passagem do elemento pela viewport (sem pin).
//   [data-on="0.56"]         ganha .is-on quando o --p da cena ancestral >= 0.56.
//   [data-fit]               escala (só reduz) para caber na altura disponível: --fit. data-fit="0.73" = fração de innerHeight.
//   [data-count]             conta de 0 até data-count (centavos) entre data-from e data-to do --p; escreve "1.234,56".
// Movimento reduzido: tudo vai para o estado final, cenas sem pin.
(function () {
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var root = document.documentElement;
  if (reduced) root.classList.add('motion-reduced');
  function brl(c) { var a = Math.abs(Math.round(c)); return (c < 0 ? '\u2212' : '') + String(Math.floor(a / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.') + ',' + String(a % 100).padStart(2, '0'); }
  function clamp(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

  // reveal
  var reveals = document.querySelectorAll('[data-reveal]');
  if (reduced || !('IntersectionObserver' in window)) reveals.forEach(function (el) { el.classList.add('is-in'); });
  else {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); } }); }, { rootMargin: '0px 0px -12% 0px', threshold: 0.12 });
    reveals.forEach(function (el) { io.observe(el); });
  }

  // scenes
  var scenes = Array.prototype.slice.call(document.querySelectorAll('[data-scene]')).map(function (el) {
    return { el: el, mode: el.dataset.scene || 'pin', on: el.querySelectorAll('[data-on]'), counts: el.querySelectorAll('[data-count]'), p: -1 };
  });
  function progress(s) {
    var r = s.el.getBoundingClientRect(), vh = window.innerHeight;
    return clamp(s.mode === 'through' ? (vh - r.top) / (vh + r.height) : -r.top / Math.max(1, r.height - vh));
  }
  function apply(s, p) {
    if (Math.abs(p - s.p) < 0.0005) return; s.p = p;
    s.el.style.setProperty('--p', p.toFixed(4));
    s.on.forEach(function (el) { el.classList.toggle('is-on', p >= parseFloat(el.dataset.on)); });
    s.counts.forEach(function (el) {
      var a = parseFloat(el.dataset.from || 0), b = parseFloat(el.dataset.to || 1);
      el.textContent = brl(parseInt(el.dataset.count, 10) * easeOut(clamp((p - a) / (b - a))));
    });
  }
  var raf = 0;
  function tick() { raf = 0; scenes.forEach(function (s) { apply(s, reduced ? 1 : progress(s)); }); }
  function schedule() { if (root.classList.contains('is-loaded')) root.classList.add('is-scrolling'); if (!raf) raf = requestAnimationFrame(tick); }

  // fit
  var fits = document.querySelectorAll('[data-fit]');
  function fit() {
    fits.forEach(function (el) {
      el.style.setProperty('--fit', 1);
      var frac = parseFloat(el.dataset.fit) || 0, avail = frac ? window.innerHeight * frac - 20 : window.innerHeight - 56;
      var h = el.offsetHeight; el.style.setProperty('--fit', h ? Math.min(1, avail / h).toFixed(4) : 1);
    });
  }

  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', function () { fit(); schedule(); });
  document.addEventListener('DOMContentLoaded', function () {
    fit(); tick();
    requestAnimationFrame(function () { root.classList.add('is-loaded'); });
  });
})();
