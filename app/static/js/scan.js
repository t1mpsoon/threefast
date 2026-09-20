/* Сканер QR заказов для кухни и администратора: камера -> код -> карточка заказа -> «Выдать». */
(function () {
  'use strict';

  var cam = document.getElementById('scan-cam');
  var video = document.getElementById('scan-video');
  var hint = document.getElementById('scan-hint');
  var toggle = document.getElementById('scan-toggle');
  var form = document.getElementById('scan-form');
  var input = document.getElementById('scan-input');
  var result = document.getElementById('scan-result');

  var NEXT = {
    confirmed: { to: 'in_progress', label: 'Начать готовить' },
    in_progress: { to: 'ready', label: 'Отметить готовым' },
    ready: { to: 'picked_up', label: 'Выдать заказ' }
  };
  var DEAD = {
    picked_up: 'Этот заказ уже выдан. Второй раз не выдаём.',
    cancelled: 'Заказ отменён. Выдавать нельзя.',
    expired: 'Заказ не забрали вовремя, он снят с выдачи.'
  };

  var stream = null, detector = null, canvas = null, running = false, paused = false, busy = false;
  var wanted = false, jsqrTried = false;

  function esc(s) { return window.EP && EP.escapeHtml ? EP.escapeHtml(String(s)) : String(s).replace(/[&<>"]/g, ''); }
  function say(text, tone) { if (window.EP && EP.say) EP.say(text, tone || 'info'); }
  function say2(text) { hint.textContent = text; }

  /* Из QR достаём номер: ссылка вида …/order?code=EX-3467 или просто EX-3467. */
  function parseCode(text) {
    text = String(text || '').trim();
    try {
      var c = new URL(text).searchParams.get('code');
      if (c) return c;
    } catch (_) { /* не ссылка */ }
    var m = text.match(/EX-?[A-Z0-9]{4}/i);
    if (m) return m[0];
    return /^[A-Z0-9]{4}$/i.test(text) ? text : null;
  }

  /* ── Камера ─────────────────────────────────────────────────────────── */
  function loadJsQR() {
    return new Promise(function (resolve) {
      if (window.jsQR) return resolve(true);
      if (jsqrTried) return resolve(false);
      jsqrTried = true;
      var s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jsQR/1.4.0/jsQR.min.js';
      s.onload = function () { resolve(Boolean(window.jsQR)); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
  }

  async function prepareDetector() {
    if (detector || window.jsQR) return true;
    if ('BarcodeDetector' in window) {
      try {
        var formats = await window.BarcodeDetector.getSupportedFormats();
        if (formats.indexOf('qr_code') !== -1) {
          detector = new window.BarcodeDetector({ formats: ['qr_code'] });
          return true;
        }
      } catch (_) { /* пробуем запасной путь */ }
    }
    return loadJsQR();
  }

  async function readFrame() {
    if (detector) {
      var found = await detector.detect(video);
      return found.length ? found[0].rawValue : null;
    }
    if (window.jsQR && video.videoWidth) {
      canvas = canvas || document.createElement('canvas');
      var w = Math.min(video.videoWidth, 640);
      var h = Math.round(video.videoHeight * (w / video.videoWidth));
      canvas.width = w; canvas.height = h;
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(video, 0, 0, w, h);
      var data = ctx.getImageData(0, 0, w, h);
      var code = window.jsQR(data.data, w, h, { inversionAttempts: 'dontInvert' });
      return code ? code.data : null;
    }
    return null;
  }

  async function loop() {
    if (!running) return;
    if (!paused && !busy && video.readyState >= 2) {
      try {
        var text = await readFrame();
        if (text) await onScanned(text);
      } catch (_) { /* кадр не прочитался — берём следующий */ }
    }
    window.setTimeout(loop, 160);
  }

  async function startCamera() {
    wanted = true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showNoCamera('Браузер не даёт доступ к камере. Введите номер вручную.');
      return;
    }
    cam.hidden = false;
    toggle.textContent = 'Выключить камеру';
    say2('Включаем камеру…');
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } }, audio: false
      });
    } catch (error) {
      showNoCamera(error && error.name === 'NotAllowedError'
        ? 'Камера запрещена. Разрешите её в настройках сайта или введите номер вручную.'
        : 'Камера недоступна. Введите номер вручную.');
      return;
    }
    video.srcObject = stream;
    try { await video.play(); } catch (_) { /* автозапуск заблокирован */ }
    var ok = await prepareDetector();
    if (!ok) { say2('Этот браузер не читает QR. Введите номер вручную.'); return; }
    running = true;
    say2('Наведите на QR-код гостя');
    loop();
  }

  function stopCamera() {
    running = false;
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    video.srcObject = null;
  }

  function showNoCamera(text) {
    stopCamera();
    wanted = false;
    cam.hidden = true;
    toggle.textContent = 'Включить камеру';
    say(text, 'warn');
  }

  toggle.addEventListener('click', function () {
    if (running || stream) { wanted = false; stopCamera(); cam.hidden = true; toggle.textContent = 'Включить камеру'; }
    else startCamera();
  });

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopCamera();
    else if (wanted && !stream) startCamera();
  });

  /* ── Поиск заказа ───────────────────────────────────────────────────── */
  async function onScanned(text) {
    var code = parseCode(text);
    if (!code) {
      paused = true;
      say2('Это не QR заказа ThreeFast');
      window.setTimeout(function () { paused = false; say2('Наведите на QR-код гостя'); }, 1800);
      return;
    }
    await lookup(code);
  }

  async function lookup(code) {
    busy = true;
    paused = true;
    say2('Ищем заказ…');
    try {
      var order = await EP.apiFetch('/api/staff/orders/by-code/' + encodeURIComponent(code));
      if (navigator.vibrate) navigator.vibrate(60);
      if (window.EPSound) window.EPSound.play('status');
      render(order);
    } catch (error) {
      renderError(error.message || 'Не удалось найти заказ.');
    } finally {
      busy = false;
    }
  }

  function resume() {
    result.innerHTML = '';
    paused = false;
    say2('Наведите на QR-код гостя');
    if (wanted && !stream) startCamera();
  }

  function renderError(message) {
    result.innerHTML = '<div class="scan-card scan-card--bad"><h2>Заказ не найден</h2><p>' + esc(message) +
      '</p><button class="btn btn--flame" type="button" data-again>Сканировать дальше</button></div>';
    result.querySelector('[data-again]').addEventListener('click', resume);
    result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function render(order) {
    var next = NEXT[order.status];
    var canNext = next && order.allowed_transitions.indexOf(next.to) !== -1;
    var dead = DEAD[order.status];
    var tone = dead ? 'bad' : order.status === 'ready' ? 'good' : 'wait';
    var banner = dead ? dead
      : order.status === 'ready' ? 'Заказ готов: можно выдавать.'
      : order.status === 'in_progress' ? 'Заказ ещё готовится.'
      : 'Заказ принят, но кухня ещё не начала готовить.';
    var items = (order.items || []).map(function (i) {
      return '<li><span>' + esc(i.item_name_snapshot) + '</span><b>×' + i.quantity + '</b></li>';
    }).join('');

    result.innerHTML =
      '<div class="scan-card scan-card--' + tone + '">' +
        '<div class="scan-card__top"><div class="scan-card__code">' + esc(order.order_code) + '</div>' +
        '<span class="badge badge--' + esc(order.status_tone || 'guest') + '">' + esc(order.status_title) + '</span></div>' +
        '<p class="scan-card__banner">' + esc(banner) + '</p>' +
        '<dl class="scan-card__info">' +
          '<div><dt>Гость</dt><dd>' + esc(order.guest_name) + ' · <a href="tel:' + esc(order.guest_phone) + '">' + esc(order.guest_phone) + '</a></dd></div>' +
          '<div><dt>Время выдачи</dt><dd>' + esc(String(order.slot_datetime).slice(11, 16)) + '</dd></div>' +
          '<div><dt>Сумма</dt><dd>' + EP.money(order.total_amount) + '</dd></div>' +
        '</dl>' +
        '<ul class="scan-card__items">' + items + '</ul>' +
        (order.note ? '<p class="scan-card__note">Примечание: ' + esc(order.note) + '</p>' : '') +
        '<div class="scan-card__acts">' +
          (canNext ? '<button class="btn ' + (order.status === 'ready' ? 'btn--flame' : 'btn--line') + '" type="button" data-advance>' + next.label + '</button>' : '') +
          '<button class="btn btn--line" type="button" data-again>Сканировать следующий</button>' +
        '</div>' +
      '</div>';

    result.querySelector('[data-again]').addEventListener('click', resume);
    var adv = result.querySelector('[data-advance]');
    if (adv) {
      adv.addEventListener('click', function () {
        EP.busy(adv, 'Сохраняем', async function () {
          try {
            await EP.apiFetch('/api/staff/orders/by-code/' + encodeURIComponent(order.order_code) + '/status', {
              method: 'PATCH', body: JSON.stringify({ new_status: next.to, version: order.version })
            });
            say(next.to === 'picked_up' ? 'Заказ ' + order.order_code + ' выдан.' : 'Статус обновлён.', 'good');
            if (window.EPSound) window.EPSound.play('success');
          } catch (error) {
            say(error.message, 'bad');
          }
          /* Перечитываем заказ: на экране всегда актуальный статус. */
          try { render(await EP.apiFetch('/api/staff/orders/by-code/' + encodeURIComponent(order.order_code))); } catch (_) {}
        });
      });
    }
    result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ── Ручной ввод ────────────────────────────────────────────────────── */
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var code = parseCode(input.value);
    if (!code) {
      if (EP.badField) EP.badField('scan-input', 'Номер выглядит так: EX-3467');
      return;
    }
    if (EP.cleanFields) EP.cleanFields(form);
    lookup(code);
  });

  startCamera();
})();
