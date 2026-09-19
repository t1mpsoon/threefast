/* Экран заказа: поиск по номеру, живой прогресс, шаринг, отмена. */
(function () {
  'use strict';

  var card = document.getElementById('order-card');
  var form = document.getElementById('code-form');
  var input = document.getElementById('code-input');
  var cancel = document.getElementById('cancel-button');
  var share = document.getElementById('share-button');
  var EVERY_MS = 15000;

  var STEP = { confirmed: 1, in_progress: 2, ready: 3, picked_up: 4 };
  var EXPLAIN = {
    confirmed: 'Кухня приняла заказ и начнёт готовить к вашей минуте.',
    in_progress: 'Заказ готовят прямо сейчас.',
    ready: 'Заказ ждёт на полке выдачи. Назовите номер — отдадим сразу.',
    picked_up: 'Заказ выдан. Приятного аппетита.',
    cancelled: 'Заказ отменён.',
    expired: 'Заказ не забрали вовремя, и он снят с выдачи.'
  };

  if (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var code = (input.value || '').trim();
      if (!/^([Ee][Xx]-?)?[A-Za-z0-9]{4}$/.test(code)) {
        EP.badField('code-input', 'Номер состоит из «EX-» и четырёх знаков, например EX-3467');
        return;
      }
      EP.cleanFields(form);
      EP.go('/order?code=' + encodeURIComponent(code));
    });
  }

  if (share) {
    share.addEventListener('click', async function () {
      var text = window.SHARE_TEXT || document.title;
      if (navigator.share) {
        try { await navigator.share({ text: text, url: window.location.href }); return; }
        catch (_) { /* гость закрыл окно шаринга */ }
      }
      try {
        await navigator.clipboard.writeText(text + ' — ' + window.location.href);
        EP.say('Ссылка на заказ скопирована. Отправьте её кому нужно.', 'good');
      } catch (_) {
        EP.say('Скопируйте ссылку из адресной строки — она ведёт на этот заказ.', 'info');
      }
    });
  }

  if (!card) return;

  var code = card.dataset.code;
  var tracker = card.querySelector('[data-progress]');
  var known = tracker ? tracker.dataset.status : null;

  function stateOf(step, index) {
    if (step > 3) return 'done';
    if (step === 3 && index === 3) return 'ready';
    if (index < step) return 'done';
    if (index === step) return 'current';
    return '';
  }

  function paint(status, tone) {
    var step = STEP[status] || 0;
    var statusTone = tone || 'guest';

    /* Тон один на весь экран: плашка, шкала и полоса панели совпадают. */
    card.dataset.tone = statusTone;

    var stateOut = card.querySelector('[data-role="state"]');
    if (stateOut) {
      stateOut.textContent = {
        confirmed: 'Принят', in_progress: 'Готовится', ready: 'Готов к выдаче',
        picked_up: 'Выдан', cancelled: 'Отменён', expired: 'Не востребован'
      }[status] || status;
      ['guest', 'active', 'done', 'lost'].forEach(function (name) {
        stateOut.classList.toggle('badge--' + name, name === statusTone);
      });
      stateOut.classList.remove('badge--glass');
    }

    if (tracker) {
      tracker.dataset.tone = statusTone;
    }

    if (tracker) {
      tracker.dataset.status = status;
      tracker.dataset.step = String(step);
      tracker.querySelectorAll('[data-stop]').forEach(function (seg) {
        var index = Number(seg.dataset.stop);
        var was = seg.dataset.state;
        var now = stateOf(step, index);
        seg.dataset.state = now;
        /* Заполнение «наливается» с инерцией, только когда статус реально сменился. */
        if (now && now !== was) {
          /* Мягкое проявление: сегмент «приезжает» из прозрачности. */
          seg.classList.remove('is-changed');
          void seg.offsetWidth;
          seg.classList.add('is-changed');
          var fill = seg.querySelector('.progress__fill');
          if (fill) {
            fill.classList.remove('is-pouring');
            void fill.offsetWidth;
            fill.classList.add('is-pouring');
          }
          /* Финальный статус: галочка дорисовывается один раз. */
          if (now === 'done') {
            var mark = seg.querySelector('.progress__done-mark');
            if (mark) {
              mark.classList.remove('is-drawing');
              void mark.offsetWidth;
              mark.classList.add('is-drawing');
            }
          }
        }
      });
    }

    var explain = card.querySelector('[data-role="explain"]');
    if (explain) explain.textContent = EXPLAIN[status] || '';

    if (cancel) cancel.hidden = !(status === 'confirmed' || status === 'in_progress');

    /* Словами — только о том, что реально поменялось. */
    if (known && known !== status) {
      var good = status === 'ready' || status === 'picked_up';
      EP.say('Заказ теперь: ' + (EXPLAIN[status] || status), good ? 'good' : 'warn',
             { title: 'Статус сменился' });
      /* Номер заказа коротко подсвечивается: видно, что данные обновились. */
      var plate = card.querySelector('.code-plate');
      if (plate) EP.nudge(plate, 'is-updated');
      if (window.EPSound) window.EPSound.play(good ? 'status' : 'tap');
    }
    known = status;
  }

  async function refresh() {
    try {
      var order = await EP.apiFetch('/api/orders/' + encodeURIComponent(code) + '/status');
      paint(order.status, order.status_tone);
    } catch (error) {
      if (error.status === 404) EP.say('Заказ с таким номером не нашли.', 'bad');
    }
  }

  if (cancel) {
    cancel.addEventListener('click', function () {
      if (!window.confirm('Отменить заказ? Кухня может уже начать готовить.')) return;
      EP.busy(cancel, 'Отменяем', async function () {
        try {
          var order = await EP.apiFetch('/api/orders/' + encodeURIComponent(code) + '/cancel',
            { method: 'POST' });
          paint(order.status);
          EP.say('Заказ отменён. Если передумаете — оформите новый.', 'info');
        } catch (error) {
          EP.say(error.message, 'bad');
        }
      });
    });
  }

  window.setInterval(refresh, EVERY_MS);

  /* Первый прогон заполнения — чтобы полоса «налилась» при открытии экрана. */
  if (tracker) {
    tracker.querySelectorAll('.progress__fill').forEach(function (fill) {
      fill.classList.add('is-pouring');
    });
  }
})();
