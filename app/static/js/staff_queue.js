/* Кухня: список заказов по времени выдачи, смена статуса текстовыми кнопками. */
(function () {
  'use strict';

  var host = document.getElementById('orders');
  var dateInput = document.getElementById('crew-date');
  var refresh = document.getElementById('crew-refresh');
  var RELOAD_MS = 20000;

  var NEXT = {
    confirmed: { to: 'in_progress', label: 'Начать готовить' },
    in_progress: { to: 'ready', label: 'Отметить готовым' },
    ready: { to: 'picked_up', label: 'Отдал гостю' }
  };

  var orders = [];

  function dishes(order) {
    return order.items.map(function (i) {
      return EP.escapeHtml(i.item_name_snapshot) + ' ×' + i.quantity;
    }).join(', ');
  }

  function rowHtml(order) {
    var next = NEXT[order.status];
    var acts = '';
    if (next && order.allowed_transitions.indexOf(next.to) !== -1) {
      acts += '<button class="link-btn" data-move="' + next.to + '" data-version="' + order.version +
        '" data-id="' + order.id + '">' + next.label + '</button>';
    }
    if (order.allowed_transitions.indexOf('cancelled') !== -1) {
      acts += '<button class="link-btn link-btn--muted" data-move="cancelled" data-version="' +
        order.version + '" data-id="' + order.id + '">Гость не придёт</button>';
    }

    return '<article class="order-row order-row--' + order.status + '"' +
      ' data-tone="' + (order.status_tone || 'guest') + '"' +
      ' data-id="' + order.id + '" data-at="' + order.slot_datetime + '">' +
      '<div>' +
        '<div class="order-row__at">' + EP.timeOf(order.slot_datetime) + '</div>' +
        '<div class="order-row__left" data-role="left">—</div>' +
      '</div>' +
      '<div>' +
        '<div class="row" style="gap:10px">' +
          '<span class="bold">' + EP.escapeHtml(order.order_code) + '</span>' +
          '<span class="badge badge--' + (order.status_tone || 'guest') + '">' +
            EP.escapeHtml(order.status_title) + '</span>' +
          '<span>' + EP.escapeHtml(order.guest_name) + '</span>' +
          '<span class="muted small">' + EP.escapeHtml(order.guest_phone) + '</span>' +
        '</div>' +
        '<div class="muted small" style="margin-top:2px">' + dishes(order) +
          ' · ' + EP.money(order.total_amount) + '</div>' +
        (order.note
          ? '<div class="order-row__note">' +
              '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
                '<path d="M12 8.5v.01M11 12h1v4h1" stroke="currentColor" stroke-width="2" ' +
                'stroke-linecap="round" stroke-linejoin="round"/>' +
                '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="2"/>' +
              '</svg>' +
              EP.escapeHtml(order.note) + '</div>'
          : '') +
      '</div>' +
      '<div class="order-row__acts">' + acts + '</div>' +
    '</article>';
  }

  function paint() {
    if (!orders.length) {
      host.innerHTML = '<div class="empty"><h3>Заказов нет</h3>' +
        '<p>На этот день очередь пуста. Новые появятся здесь сами.</p></div>';
      paintMeters();
      return;
    }
    host.innerHTML = orders.map(rowHtml).join('');
    paintMeters();
    tick();
  }

  function paintMeters() {
    document.getElementById('meter-total').textContent = String(orders.length);
    document.getElementById('meter-ready').textContent = String(
      orders.filter(function (o) { return o.status === 'ready'; }).length
    );
    var next = orders[0];
    if (!next) {
      document.getElementById('meter-next').textContent = '—';
      document.getElementById('meter-next-note').textContent = 'нет заказов';
      return;
    }
    document.getElementById('meter-next').textContent = EP.timeOf(next.slot_datetime);
    document.getElementById('meter-next-note').textContent =
      next.order_code + ', осталось ' + countdownText(EP.secondsLeft(next.slot_datetime));
  }

  function countdownText(seconds) {
    return seconds < 0 ? 'просрочен на ' + EP.countdown(seconds).slice(1) : EP.countdown(seconds);
  }

  function tick() {
    var now = Date.now();
    host.querySelectorAll('.order-row').forEach(function (node) {
      var seconds = Math.round((new Date(node.dataset.at).getTime() - now) / 1000);
      var out = node.querySelector('[data-role="left"]');
      if (!out) return;
      out.textContent = countdownText(seconds);
      out.classList.toggle('is-late', seconds < 0);
      node.classList.toggle('order-row--late', seconds <= 300 && node.dataset.status !== 'ready');
    });
    paintMeters();
  }

  async function load() {
    try {
      orders = await EP.apiFetch('/api/staff/orders?date=' + encodeURIComponent(dateInput.value));
      paint();
    } catch (error) {
      if (error.status === 401) { EP.go('/login?next=/staff'); return; }
      host.innerHTML = '<div class="empty">' + EP.escapeHtml(error.message) + '</div>';
    }
  }

  async function move(id, target, version, button) {
    await EP.busy(button, '…', async function () {
      try {
        await EP.apiFetch('/api/staff/orders/' + id + '/status', {
          method: 'PATCH',
          body: JSON.stringify({ new_status: target, version: version })
        });
        await load();
        EP.say('Статус обновлён — гость увидит изменение.', 'good');
      } catch (error) {
        if (error.status === 409) {
          EP.say('Кто-то из смены уже изменил этот заказ. Показываем свежие данные.', 'warn');
          await load();
          return;
        }
        EP.say(error.message, 'bad');
      }
    });
  }

  host.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-move]');
    if (!button) return;
    move(button.dataset.id, button.dataset.move, Number(button.dataset.version), button);
  });

  refresh.addEventListener('click', load);
  dateInput.addEventListener('change', load);

  var out = document.getElementById('crew-out');
  if (out) {
    out.addEventListener('click', async function (event) {
      event.preventDefault();
      try { await EP.apiFetch('/api/auth/logout', { method: 'POST' }); } catch (_) { /* ignore */ }
      EP.go('/login');
    });
  }

  load();
  window.setInterval(tick, 1000);
  window.setInterval(load, RELOAD_MS);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
})();
