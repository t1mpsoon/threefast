/* Шторка оформления: имя, телефон, оплата, сводка и постановка заказа на кухню. */
(function () {
  'use strict';

  var placeId = window.PLACE_ID;
  var form = document.getElementById('checkout-form');
  if (!form) return;

  var sheet = window.EP_SHEETS[1];
  var summary = document.getElementById('checkout-summary');
  var totalOut = document.getElementById('checkout-total');
  var whenOut = document.getElementById('checkout-when');
  var submit = document.getElementById('checkout-submit');
  var nameInput = document.getElementById('guest-name');
  var phoneInput = document.getElementById('guest-phone');
  var note = document.getElementById('guest-note');
  var noteCount = document.getElementById('note-count');
  var tableInput = document.getElementById('guest-table');
  var KEY_CELL = 'express_pickup_pending_v1';

  /* Метка со QR-плаката: `?src=table5` — столик подставляем сразу, гостю
     остаётся только подтвердить. Ссылку даёт страница плаката. */
  if (tableInput) {
    var fromPoster = /^table(\d{1,2})$/i.exec(
      (new URLSearchParams(window.location.search).get('src') || '').trim()
    );
    if (fromPoster) tableInput.value = String(Number(fromPoster[1]));
  }

  /* Пока заказ отправляется, кнопку нельзя включать обратно. Иначе правка
     состава в сводке (она шлёт cart:changed) снова делала кнопку активной,
     и гость отправлял второй заказ — в базе оказывались два. */
  var sending = false;

  /* Счётчик под примечанием: видно, сколько места осталось. */
  if (note && noteCount) {
    note.addEventListener('input', function () {
      var left = 200 - note.value.length;
      noteCount.textContent = note.value.length ? 'Осталось ' + left : '';
    });
  }

  /* ── Отрисовка сводки ──────────────────────────────────────────────────── */

  /* «Добавьте к заказу»: напитки и десерты одним касанием. Поднимает средний чек. */
  function renderUpsell() {
    var summary = document.getElementById('checkout-summary');
    if (!summary || !summary.parentNode) return;
    var old = document.getElementById('upsell');
    if (old) old.remove();
    if (!Cart.dishes().length) return;
    var picks = [];
    document.querySelectorAll('[data-section]').forEach(function (section) {
      if (!/напит|десерт|чай|кофе|сладк|выпечк/i.test(section.dataset.section)) return;
      section.querySelectorAll('[data-dish]').forEach(function (card) {
        if (!Cart.quantityOf(card.dataset.dish) && picks.length < 3) picks.push(card);
      });
    });
    if (!picks.length) return;
    var box = document.createElement('div');
    box.id = 'upsell';
    box.className = 'upsell';
    box.innerHTML = '<div class="upsell__title">Добавьте к заказу</div>';
    picks.forEach(function (card) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip';
      b.textContent = '+ ' + card.dataset.name + ' · ' + EP.money(Number(card.dataset.price));
      b.addEventListener('click', function () {
        Cart.add({ id: card.dataset.dish, name: card.dataset.name, price: card.dataset.price, cooks: card.dataset.cooks }, 1);
      });
      box.appendChild(b);
    });
    summary.parentNode.insertBefore(box, summary.nextSibling);
  }
  document.addEventListener('cart:changed', renderUpsell);
  renderUpsell();

  var shownTotal = 0;

  function paint() {
    var dishes = Cart.dishes();
    if (!dishes.length) {
      summary.innerHTML = '<p class="muted small">Заказ пуст.</p>';
      shownTotal = 0;
    } else if (!summary.querySelector('[data-sum]')) {
      summary.innerHTML = Cart.summaryHtml();
      shownTotal = Cart.sum();
      /* Строки въезжают по очереди: сводка собирается на глазах. */
      summary.querySelectorAll('[data-sum]').forEach(function (row, index) {
        row.classList.add('summary__row--in');
        row.style.animationDelay = (index * 45) + 'ms';
        window.setTimeout(function () { row.classList.remove('summary__row--in'); }, 300 + index * 45);
      });
    } else {
      Cart.paintSummary(summary);
    }

    var total = Cart.sum();
    var note = summary.querySelector('.discount-note');
    if (Cart.discount() && dishes.length) {
      if (!note) { note = document.createElement('p'); note.className = 'discount-note'; summary.appendChild(note); }
      note.textContent = 'Скидка −' + Cart.discount() + '% за выдачу вне часов пик: вы сэкономили ' +
        EP.money(Cart.gross() - total);
    } else if (note) { note.remove(); }
    if (total !== shownTotal) {
      EP.countUp(totalOut, shownTotal, total, function (value) { return EP.money(value); }, 320);
      if (shownTotal) EP.nudge(totalOut, 'pulse');
      shownTotal = total;
    } else {
      totalOut.textContent = EP.money(total);
    }

    var minute = Cart.minute();
    whenOut.textContent = minute.at
      ? 'Заберёте ' + EP.whenOf(minute.at)
      : 'Время выдачи не выбрано';
    var filled = Cart.portions() > 0 && Boolean(minute.at);
    submit.disabled = sending || !filled;
    paintSteps();
  }

  /* Кнопки количества прямо в сводке: убрать и добавить, не выходя из шторки. */
  summary.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-sum-act]');
    /* Состав заказа уже ушёл на кухню — менять его поздно. */
    if (!button || sending) return;
    var id = Number(button.dataset.id);
    var dish = Cart.dishes().filter(function (one) { return one.id === id; })[0];
    if (!dish) return;
    var action = button.dataset.sumAct;
    /* «×» убирает позицию целиком: минус по одной порции для этого неудобен. */
    var delta = action === 'plus' ? 1 : (action === 'drop' ? -dish.quantity : -1);
    var result = Cart.add(dish, delta);
    if (!result.ok) {
      EP.say(result.why, 'warn', { title: 'Столько не возьмём' });
    }
  });

  /* Шаги оформления: состав → время → данные. Видно, что осталось заполнить. */
  function paintSteps() {
    var steps = document.getElementById('checkout-steps');
    if (!steps) return;
    var done = {
      items: Cart.portions() > 0,
      time: Boolean(Cart.minute().at),
      guest: (nameInput.value || '').trim().length > 1 && (phoneInput.value || '').trim().length > 5
    };
    steps.querySelectorAll('[data-step]').forEach(function (node) {
      var key = node.dataset.step;
      var ready = done[key];
      node.classList.toggle('is-done', ready);
      /* Только что выполненный шаг мягко подтверждается. */
      if (ready && node.dataset.ready !== 'yes') {
        node.dataset.ready = 'yes';
        EP.nudge(node, 'is-just');
      } else if (!ready) {
        node.dataset.ready = 'no';
      }
    });
  }

  /* ── Ключ идемпотентности: двойное нажатие не создаст второй заказ ─────── */

  function fingerprint() {
    var lines = Cart.dishes().map(function (d) { return d.id + 'x' + d.quantity; }).sort().join(',');
    return placeId + '|' + (Cart.minute().at || '') + '|' + lines;
  }

  function pendingKey() {
    var stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(KEY_CELL) || 'null'); } catch (_) { stored = null; }
    var print = fingerprint();
    if (stored && stored.print === print && stored.key) return stored.key;
    var key = (window.crypto && window.crypto.randomUUID)
      ? window.crypto.randomUUID().replace(/-/g, '')
      : Array.from({ length: 32 }, function () {
          return Math.floor(Math.random() * 16).toString(16);
        }).join('');
    try { sessionStorage.setItem(KEY_CELL, JSON.stringify({ print: print, key: key })); } catch (_) { /* ignore */ }
    return key;
  }

  function forgetKey() {
    try { sessionStorage.removeItem(KEY_CELL); } catch (_) { /* ignore */ }
  }

  /* ── Проверки ──────────────────────────────────────────────────────────── */

  function phone(raw) {
    var digits = String(raw || '').replace(/\D/g, '');
    if (digits.length === 11 && (digits[0] === '7' || digits[0] === '8')) return '+7' + digits.slice(1);
    if (digits.length === 10) return '+7' + digits;
    return null;
  }

  function check() {
    var ok = true;
    EP.cleanFields(form);

    var name = nameInput.value.trim().replace(/\s+/g, ' ');
    if (name.length < 2) {
      EP.badField('guest-name', 'Напишите имя — позовём вас, когда заказ будет готов');
      ok = false;
    }
    var normalized = phone(phoneInput.value);
    if (!normalized) {
      EP.badField('guest-phone', 'Нужен номер вида +7 701 123 45 67, иначе не сможем предупредить о задержке');
      ok = false;
    }
    var table = tableNumber();
    if (table === false) {
      EP.badField('guest-table', 'Номер столика — от 1 до 60. Оставьте пустым, если заказ на вынос');
      ok = false;
    }
    return ok ? { name: name, phone: normalized, table: table || null } : null;
  }

  /* Столик необязателен: пусто — заказ на вынос. Но если номер назван,
     он должен быть номером, иначе кухня не поймёт, куда нести. */
  function tableNumber() {
    if (!tableInput) return null;
    var raw = String(tableInput.value).trim();
    if (!raw) return null;
    var number = Number(raw);
    return Number.isInteger(number) && number >= 1 && number <= 60 ? number : false;
  }

  /* Три плавающие точки на время отправки. */
  function busyDots() {
    sending = true;
    submit.innerHTML = '<span class="dots" aria-label="Отправляем"><i></i><i></i><i></i></span>';
    submit.disabled = true;
  }

  function restoreButton() {
    sending = false;
    submit.innerHTML = 'Оформить заказ · <span id="checkout-total">' + EP.money(Cart.sum()) + '</span>';
    totalOut = document.getElementById('checkout-total');
    paint();
  }

  /* ── Отправка ──────────────────────────────────────────────────────────── */

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    /* Вторая отправка поверх летящей — это второй заказ. */
    if (sending) return;
    EP.clearNotices();

    var values = check();
    if (!values) {
      EP.say('Проверьте имя и телефон — без них заказ не примем.', 'bad');
      /* Переводим фокус на первое проблемное поле: иначе гость слышит, что
         что-то не так, но не знает, куда смотреть. */
      EP.focusFirstBad(form);
      return;
    }
    if (Cart.portions() === 0) {
      EP.say('В заказе ничего нет. Вернитесь в меню и выберите блюда.', 'bad');
      return;
    }
    if (!Cart.minute().at) {
      EP.say('Время выдачи не выбрано.', 'bad');
      window.TimeSheet.open();
      return;
    }

    var body = {
      establishment_id: placeId,
      slot_datetime: Cart.minute().at,
      guest_name: values.name,
      guest_phone: values.phone,
      items: Cart.dishes().map(function (d) { return { menu_item_id: d.id, quantity: d.quantity }; }),
      payment_method: form.querySelector('input[name="payment_method"]:checked').value,
      note: (note ? note.value.trim() : '') || null,
      table_number: values.table,
      idempotency_key: pendingKey()
    };

    busyDots();
    EP.apiFetch('/api/orders', { method: 'POST', body: JSON.stringify(body) })
      .then(function (order) {
        try {
          localStorage.setItem('ep_last_order', JSON.stringify({
            place: Cart.state().place,
            dishes: Cart.dishes()
          }));
        } catch (_) { /* приватный режим */ }
        Cart.empty();
        forgetKey();
        if (window.EPSound) window.EPSound.play('success');
        EP.go('/order?code=' + encodeURIComponent(order.order_code) + '&fresh=1');
      })
      .catch(function (error) {
        restoreButton();
        /* Минуту заняли между выбором и подтверждением — возвращаем к табло,
           заказ в корзине сохраняется. */
        if (error.status === 409 && error.code === 'slot_unavailable') {
          Cart.setMinute(null, null);
          forgetKey();
          sheet.close();
          EP.say('Эту минуту только что заняли. Выберите другую — заказ сохранился.',
                 'warn', { title: 'Минута ушла' });
          window.setTimeout(function () { window.TimeSheet.open(); }, 340);
          return;
        }
        var fields = (error.payload && error.payload.fields) || {};
        var map = { guest_name: 'guest-name', guest_phone: 'guest-phone' };
        Object.keys(fields).forEach(function (key) {
          if (map[key]) EP.badField(map[key], fields[key]);
        });
        EP.say(error.message, 'bad', { title: 'Заказ не принят' });
      });
  });

  document.addEventListener('cart:changed', paint);

  /* Данные гостя тоже двигают шаги оформления. */
  [nameInput, phoneInput].forEach(function (input) {
    input.addEventListener('input', paintSteps);
    input.addEventListener('change', paintSteps);
  });

  window.CheckoutSheet = {
    open: function () {
      paint();
      sheet.open();
    }
  };

  paint();
})();
