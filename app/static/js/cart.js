/* Корзина-заказ: состояние и отрисовка строк меню и сводки.
   Заказ живёт в браузере до оформления — на сервере ничего не создаётся. */
(function () {
  'use strict';

  var KEY = 'express_pickup_order_v1';
  var MAX_PORTIONS = 20;
  var MAX_DISHES = 15;

  function blank() {
    return { place: null, dishes: [], minute: null, minuteLabel: null, code: null };
  }

  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return blank();
      var parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.dishes)) return blank();
      return parsed;
    } catch (_) {
      return blank();
    }
  }

  function write(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* приватный режим */ }
    announce();
  }

  function announce() {
    var state = read();
    document.dispatchEvent(new CustomEvent('cart:changed', { detail: state }));
  }

  window.addEventListener('storage', function (event) {
    if (event.key === KEY) announce();
  });

  function portions(state) {
    return (state || read()).dishes.reduce(function (sum, d) { return sum + d.quantity; }, 0);
  }

  function total(state) {
    return (state || read()).dishes.reduce(function (sum, d) { return sum + d.price * d.quantity; }, 0);
  }

  function portionsLabel(n) {
    return n + ' ' + EP.plural(n, 'позиция', 'позиции', 'позиций');
  }

  /* Привязка корзины к заведению.

     Заказ собирается в одном заведении, поэтому при переходе в другое корзина
     очищается. Возвращаем признак, что очистка произошла: без него гость
     терял выбранное молча и не понимал, куда делся заказ. */
  function bind(placeId) {
    var state = read();
    if (state.place !== placeId) {
      var lost = portions(state);
      var wasSet = Boolean(state.place) && lost > 0;
      write(Object.assign(blank(), { place: placeId }));
      var result = read();
      result.dropped = wasSet ? lost : 0;
      return result;
    }
    state.dropped = 0;
    return state;
  }

  function add(dish, delta) {
    var state = read();
    var found = null;
    state.dishes.forEach(function (d) { if (d.id === Number(dish.id)) found = d; });

    if (!found && state.dishes.length >= MAX_DISHES) {
      return { ok: false, why: 'В один заказ входит не больше ' + MAX_DISHES + ' блюд. Уберите что-нибудь или оформите второй заказ.' };
    }
    var next = (found ? found.quantity : 0) + (delta || 1);
    if (next > MAX_PORTIONS) {
      return { ok: false, why: 'Больше ' + MAX_PORTIONS + ' порций одного блюда в заказ не помещается.' };
    }

    if (next <= 0) {
      state.dishes = state.dishes.filter(function (d) { return d.id !== Number(dish.id); });
    } else if (found) {
      found.quantity = next;
      found.price = Number(dish.price);
      found.name = dish.name;
    } else {
      state.dishes.push({
        id: Number(dish.id),
        name: dish.name,
        price: Number(dish.price),
        cooks: Number(dish.cooks || 0),
        quantity: next
      });
    }
    write(state);
    return { ok: true, quantity: next };
  }

  function setMinute(iso, label) {
    var state = read();
    state.minute = iso;
    state.minuteLabel = label || null;
    write(state);
  }

  function setCode(code) {
    var state = read();
    state.code = code;
    write(state);
  }

  function empty() {
    var state = read();
    state.dishes = [];
    state.minute = null;
    state.minuteLabel = null;
    state.code = null;
    write(state);
  }

  function cooksFor() {
    return read().dishes.reduce(function (max, d) { return Math.max(max, d.cooks || 0); }, 0);
  }

  /* Сводка заказа: строки «название — количество — цена».
     У каждой строки есть data-id, поэтому перерисовка обновляет её на месте,
     а не пересобирает весь список: строки не мигают и не теряют анимацию. */
  function summaryHtml() {
    return read().dishes.map(function (dish) {
      return '<div class="summary__row" data-sum="' + dish.id + '">' +
        '<span class="summary__name">' + EP.escapeHtml(dish.name) + '</span>' +
        '<span class="summary__side">' +
          '<span class="summary__qty">×' + dish.quantity + '</span>' +
          '<span class="summary__sum">' + EP.money(dish.price * dish.quantity) + '</span>' +
          controls(dish) +
        '</span>' +
      '</div>';
    }).join('');
  }

  /* Количество меняется прямо в оформлении: вернуться в меню не нужно. */
  function controls(dish) {
    return '<span class="summary__acts">' +
      '<button type="button" class="summary__btn" data-sum-act="less" data-id="' + dish.id + '"' +
        ' aria-label="Убрать порцию «' + EP.escapeHtml(dish.name) + '»">−</button>' +
      '<button type="button" class="summary__btn" data-sum-act="plus" data-id="' + dish.id + '"' +
        ' aria-label="Добавить порцию «' + EP.escapeHtml(dish.name) + '»">+</button>' +
      '<button type="button" class="summary__btn summary__btn--drop" data-sum-act="drop"' +
        ' data-id="' + dish.id + '" aria-label="Убрать «' + EP.escapeHtml(dish.name) +
        '» из заказа">×</button>' +
    '</span>';
  }

  /* Обновляет готовую сводку: новые строки въезжают, убранные уезжают,
     количества и суммы меняются на месте. */
  function paintSummary(host) {
    if (!host) return;
    var dishes = read().dishes;
    var known = {};
    dishes.forEach(function (dish) { known[dish.id] = true; });

    /* Убираем то, чего больше нет в заказе. */
    Array.prototype.slice.call(host.querySelectorAll('[data-sum]')).forEach(function (row) {
      if (known[row.dataset.sum]) return;
      row.classList.add('summary__row--out');
      window.setTimeout(function () { row.remove(); }, 180);
    });

    dishes.forEach(function (dish) {
      var row = host.querySelector('[data-sum="' + dish.id + '"]');
      var sum = EP.money(dish.price * dish.quantity);
      if (!row) {
        var made = document.createElement('div');
        made.className = 'summary__row summary__row--in';
        made.dataset.sum = dish.id;
        made.innerHTML =
          '<span class="summary__name">' + EP.escapeHtml(dish.name) + '</span>' +
          '<span class="summary__side">' +
            '<span class="summary__qty">×' + dish.quantity + '</span>' +
            '<span class="summary__sum">' + sum + '</span>' +
            controls(dish) +
          '</span>';
        host.appendChild(made);
        window.setTimeout(function () { made.classList.remove('summary__row--in'); }, 260);
        return;
      }
      var qty = row.querySelector('.summary__qty');
      var money = row.querySelector('.summary__sum');
      if (qty && qty.textContent !== '×' + dish.quantity) {
        qty.textContent = '×' + dish.quantity;
        if (window.EP && EP.nudge) EP.nudge(qty, 'pulse');
      }
      if (money && money.textContent !== sum) money.textContent = sum;
    });
  }

  window.Cart = {
    MAX_PORTIONS: MAX_PORTIONS,
    MAX_DISHES: MAX_DISHES,
    bind: bind,
    state: read,
    dishes: function () { return read().dishes; },
    portions: portions,
    portionsLabel: portionsLabel,
    sum: total,
    quantityOf: function (id) {
      var found = null;
      read().dishes.forEach(function (d) { if (d.id === Number(id)) found = d; });
      return found ? found.quantity : 0;
    },
    cooksFor: cooksFor,
    add: add,
    setMinute: setMinute,
    setCode: setCode,
    minute: function () { return { at: read().minute, label: read().minuteLabel }; },
    empty: empty,
    summaryHtml: summaryHtml,
    paintSummary: paintSummary,
    announce: announce
  };
})();
