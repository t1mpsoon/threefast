/* Экран заказа: поиск по номеру, живой прогресс, шаринг, отмена. */
(function () {
  'use strict';

  var card = document.getElementById('order-card');
  var form = document.getElementById('code-form');
  var input = document.getElementById('code-input');
  var cancel = document.getElementById('cancel-button');
  var share = document.getElementById('share-button');

  /* QR заказа: рисуется в браузере, без внешних сервисов. */
  var qrBox = document.getElementById('order-qr');
  var qrImg = document.getElementById('order-qr-img');
  if (qrBox && qrImg && window.EPQR) {
    try {
      qrImg.innerHTML = window.EPQR.svg(
        window.location.origin + '/order?code=' + encodeURIComponent(qrBox.dataset.code),
        { size: 168, label: 'QR-код заказа ' + qrBox.dataset.code });
    } catch (_) { qrBox.hidden = true; }
  }

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

  var calBtn = document.getElementById('calendar-button');
  if (calBtn) {
    /* Файл .ics открывается в любом календаре: напоминание за 15 минут. */
    calBtn.addEventListener('click', function () {
      var d = calBtn.dataset, start = d.start;
      var end = new Date(new Date(d.iso).getTime() + 15 * 60000);
      var pad = function (n) { return String(n).padStart(2, '0'); };
      var endStr = end.getFullYear() + pad(end.getMonth() + 1) + pad(end.getDate()) + 'T' +
        pad(end.getHours()) + pad(end.getMinutes()) + '00';
      var ics = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ThreeFast//RU', 'BEGIN:VEVENT',
        'UID:' + d.code + '@threefast', 'DTSTAMP:' + start + 'Z',
        'DTSTART:' + start, 'DTEND:' + endStr,
        'SUMMARY:Заказ ' + d.code + ' — ' + d.place, 'LOCATION:' + (d.address || d.place),
        'BEGIN:VALARM', 'TRIGGER:-PT15M', 'ACTION:DISPLAY', 'DESCRIPTION:Скоро выдача заказа', 'END:VALARM',
        'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([ics], { type: 'text/calendar;charset=utf-8' }));
      a.download = 'zakaz-' + d.code + '.ics';
      document.body.appendChild(a); a.click(); a.remove();
    });

    /* Живой отсчёт до выдачи под временем. */
    var minuteEl = card && card.querySelector('[data-role="minute"]');
    if (minuteEl) {
      var eta = document.createElement('div');
      eta.className = 'muted small eta';
      minuteEl.parentNode.appendChild(eta);
      var tickEta = function () {
        var mins = Math.round((new Date(calBtn.dataset.iso).getTime() - Date.now()) / 60000);
        eta.textContent = mins > 1 ? 'Через ' + mins + ' ' + EP.plural(mins, 'минуту', 'минуты', 'минут')
          : mins >= -1 ? 'Пора идти за заказом' : '';
      };
      tickEta();
      window.setInterval(tickEta, 30000);
    }
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

  function paint(status, tone, headline) {
    var step = STEP[status] || 0;
    var statusTone = tone || 'guest';

    /* Тон один на весь экран: плашка, шкала и полоса панели совпадают. */
    card.dataset.tone = statusTone;

    /* Заголовок тоже говорит правду: «принят» → «готовят» → «готов!».
       Формулировку даёт сервер — та же строка, что и у кухни. */
    var head = card.querySelector('[data-role="headline"]');
    if (head && headline) head.textContent = 'Заказ ' + code + ' ' + headline;

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

    if (qrBox) qrBox.hidden = !(status === 'confirmed' || status === 'in_progress' || status === 'ready');

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
      if (status === 'ready' && window.EPDialog && !document.hidden && !EPDialog.isOpen()) {
        EPDialog.open({ icon: '🎉', title: 'Заказ готов!', text: 'Назовите этот номер на выдаче:', code: code,
          actions: [{ label: 'Иду забирать', kind: 'primary' }] });
      }
      if (window.EPNotify && (status === 'ready' || status === 'in_progress')) {
        window.EPNotify.show(status === 'ready' ? 'Заказ готов! 🍽' : 'Заказ готовится',
          (status === 'ready' ? 'Назовите номер ' : 'Номер ') + code, code);
      }
    }
    known = status;
  }

  /* ── Живая синхронизация с кухней ──────────────────────────────────────
     Пока заказ в работе, статус спрашиваем каждые 5 секунд: кухня меняет его
     у себя, гость видит это без перезагрузки. Как только заказ завершён,
     опрос прекращается — дальше меняться нечему. В скрытой вкладке сервер
     не дёргаем: при возврате статус обновляется сразу. */
  var POLL_MS = 5000;
  var pollTimer = null;
  var stopped = false;

  function schedulePoll() {
    if (pollTimer) { window.clearTimeout(pollTimer); pollTimer = null; }
    if (stopped || document.hidden) return;
    pollTimer = window.setTimeout(async function () {
      pollTimer = null;
      await refresh();
      schedulePoll();
    }, POLL_MS);
  }

  async function refresh() {
    try {
      var order = await EP.apiFetch('/api/orders/' + encodeURIComponent(code) + '/status');
      paint(order.status, order.status_tone, order.status_headline);
      /* is_active приходит с сервера: выдан, отменён или снят — опрос не нужен. */
      if (!order.is_active) stopped = true;
    } catch (error) {
      if (error.status === 404) {
        stopped = true;
        EP.say('Заказ с таким номером не нашли.', 'bad');
      }
    }
  }

  if (cancel) {
    cancel.addEventListener('click', async function () {
      var sure = window.EPDialog
        ? await EPDialog.confirm({ icon: '⚠️', title: 'Отменить заказ?', text: 'Кухня могла уже начать готовить. Отмену нельзя вернуть.', ok: 'Да, отменить', cancel: 'Оставить заказ', danger: true })
        : window.confirm('Отменить заказ? Кухня может уже начать готовить.');
      if (!sure) return;
      EP.busy(cancel, 'Отменяем', async function () {
        try {
          var order = await EP.apiFetch('/api/orders/' + encodeURIComponent(code) + '/cancel',
            { method: 'POST' });
          paint(order.status, order.status_tone, order.status_headline);
          stopped = true;
          EP.say('Заказ отменён. Если передумаете — оформите новый.', 'info');
        } catch (error) {
          EP.say(error.message, 'bad');
        }
      });
    });
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { schedulePoll(); return; }  /* снимет таймер */
    refresh().then(schedulePoll);
  });
  if (window.EPNotify && known && known !== 'picked_up' && known !== 'cancelled' && known !== 'expired') {
    window.EPNotify.ask(card);
  }

  /* Заказ уже завершён — следить не за чем; иначе начинаем опрос. */
  if (known === 'picked_up' || known === 'cancelled' || known === 'expired') stopped = true;
  schedulePoll();

  /* Первый прогон заполнения — чтобы полоса «налилась» при открытии экрана. */
  if (tracker) {
    tracker.querySelectorAll('.progress__fill').forEach(function (fill) {
      fill.classList.add('is-pouring');
    });
  }
})();
