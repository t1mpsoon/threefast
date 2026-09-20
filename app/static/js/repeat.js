/* «Повторить прошлый заказ»: одна кнопка для постоянных гостей. Данные только в браузере. */
(function () {
  'use strict';
  if (!window.Cart) return;
  var m = location.pathname.match(/^\/e\/(\d+)\/menu/);
  var last;
  try { last = JSON.parse(localStorage.getItem('ep_last_order') || 'null'); } catch (_) { last = null; }
  if (!m || !last || String(last.place) !== m[1] || !last.dishes || !last.dishes.length) return;
  var anchor = document.querySelector('.menu-cats');
  if (!anchor) return;

  function build() {
    if (document.getElementById('repeat-order')) return;
    var available = last.dishes.filter(function (d) {
      return document.querySelector('[data-dish="' + d.id + '"]');
    });
    if (!available.length || Cart.portions() > 0) return;
    var sum = available.reduce(function (s, d) { return s + d.price * d.quantity; }, 0);
    var box = document.createElement('div');
    box.id = 'repeat-order';
    box.className = 'repeat-order';
    box.innerHTML = '<div><b>Как в прошлый раз</b><span>' +
      available.map(function (d) { return d.quantity + '× ' + d.name; }).join(', ') +
      ' · ' + sum.toLocaleString('ru-RU') + ' ₸</span></div>' +
      '<button class="btn btn--sm" type="button">Повторить</button>';
    box.querySelector('button').addEventListener('click', function () {
      available.forEach(function (d) {
        var card = document.querySelector('[data-dish="' + d.id + '"]');
        Cart.add({ id: d.id, name: card.dataset.name, price: card.dataset.price, cooks: card.dataset.cooks }, d.quantity);
      });
      box.remove();
    });
    anchor.parentNode.insertBefore(box, anchor);
  }
  build();
  document.addEventListener('cart:changed', function () {
    var b = document.getElementById('repeat-order');
    if (b && Cart.portions() > 0) b.remove();
  });
})();
