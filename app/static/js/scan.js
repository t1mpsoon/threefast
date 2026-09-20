/* Сканер QR заказов для кухни и администратора: камера -> код -> карточка заказа -> «Выдать».

   Декодеров два, и это главное для совместимости:
   1) встроенный `BarcodeDetector` — есть в Chrome/Edge на Android, macOS и ChromeOS,
      работает быстро и ничего не грузит;
   2) `jsQR` из /static/js/vendor — чистый JS на canvas, работает в остальных браузерах
      (Safari, Firefox, Chrome на Windows), включая те, где камеры нет вовсе:
      фото QR и ручной ввод номера доступны всегда.

   Раньше запасной декодер тянулся с cdnjs по ссылке, которой там нет (404), поэтому
   сканер молча работал только там, где есть BarcodeDetector.
*/
(function () {
  'use strict';

  var cam = document.getElementById('scan-cam');
  var video = document.getElementById('scan-video');
  var hint = document.getElementById('scan-hint');
  var toggle = document.getElementById('scan-toggle');
  var form = document.getElementById('scan-form');
  var input = document.getElementById('scan-input');
  var result = document.getElementById('scan-result');
  var file = document.getElementById('scan-file');

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

  /* Больше кадр — мельче модуль QR, который ещё читается. 800 хватает
     и на плотные коды, и на слабые телефоны. */
  var MAX_SIDE = 800;
  /* Если код не находится, пробуем инвертированный вариант: некоторые
     показывают QR светлым по тёмному (тёмная тема). */
  var INVERT_AFTER_MS = 1200;

  var stream = null, detector = null, canvas = null, running = false, paused = false, busy = false;
  var wanted = false, nativeMisses = 0, lastHit = 0, jsqrLoading = null, starting = false;

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

  /* ── Декодеры ───────────────────────────────────────────────────────── */
  function loadJsQR() {
    if (window.jsQR) return Promise.resolve(true);
    if (jsqrLoading) return jsqrLoading;
    jsqrLoading = new Promise(function (resolve) {
      /* Скрипт уже подключён шаблоном; это запасной путь на случай,
         если тег не успел загрузиться или его вырезал прокси. */
      var s = document.createElement('script');
      s.src = '/static/js/vendor/jsQR.min.js';
      s.onload = function () { resolve(Boolean(window.jsQR)); };
      s.onerror = function () { resolve(false); };
      document.head.appendChild(s);
    });
    return jsqrLoading;
  }

  async function prepareDecoder() {
    if (detector || window.jsQR) return true;
    if ('BarcodeDetector' in window) {
      try {
        var formats = await window.BarcodeDetector.getSupportedFormats();
        if (formats.indexOf('qr_code') !== -1) {
          detector = new window.BarcodeDetector({ formats: ['qr_code'] });
          return true;
        }
      } catch (_) { /* уходим на jsQR */ }
    }
    return loadJsQR();
  }

  function drawToCanvas(source, width, height) {
    var scale = Math.min(1, MAX_SIDE / Math.max(width, height));
    var w = Math.max(1, Math.round(width * scale));
    var h = Math.max(1, Math.round(height * scale));
    canvas = canvas || document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, w, h);
    return { ctx: ctx, w: w, h: h };
  }

  function decodeCanvas(ctx, w, h, allowInvert) {
    if (!window.jsQR) return null;
    var image = ctx.getImageData(0, 0, w, h);
    var code = window.jsQR(image.data, w, h, {
      inversionAttempts: allowInvert ? 'attemptBoth' : 'dontInvert'
    });
    return code ? code.data : null;
  }

  function decodeImage(source, width, height, allowInvert) {
    /* Один и тот же путь для кадра камеры и для загруженного фото. */
    var drawn = drawToCanvas(source, width, height);
    return decodeCanvas(drawn.ctx, drawn.w, drawn.h, allowInvert);
  }

  async function readFrame() {
    if (detector) {
      try {
        var found = await detector.detect(video);
        if (found && found.length) { nativeMisses = 0; return found[0].rawValue; }
        return null;
      } catch (_) {
        /* Браузер объявил BarcodeDetector, но вызвать его не может:
           после третьей осечки насовсем уходим на jsQR. */
        if (++nativeMisses >= 3) { detector = null; await loadJsQR(); }
        return null;
      }
    }
    if (!window.jsQR || !video.videoWidth) return null;
    var allowInvert = Date.now() - lastHit > INVERT_AFTER_MS;
    return decodeImage(video, video.videoWidth, video.videoHeight, allowInvert);
  }

  async function loop() {
    if (!running) return;
    if (!paused && !busy && video.readyState >= 2) {
      try {
        var text = await readFrame();
        if (text) { lastHit = Date.now(); await onScanned(text); }
      } catch (_) { /* кадр не прочитался — берём следующий */ }
    }
    window.setTimeout(loop, 160);
  }

  /* ── Камера ─────────────────────────────────────────────────────────── */
  function cameraProblem(error) {
    var name = (error && error.name) || '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      return 'Камера запрещена. Разрешите её в настройках сайта или загрузите фото QR.';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      return 'Камера не найдена. Загрузите фото QR или введите номер.';
    }
    if (name === 'NotReadableError') {
      return 'Камеру занял другое приложение. Закройте его или загрузите фото QR.';
    }
    return 'Камера недоступна. Загрузите фото QR или введите номер.';
  }

  async function startCamera() {
    /* Защита от двойного запуска: пока камера поднимается, повторное нажатие
       кнопки поднимало второй поток и ломало первый (play() падал с AbortError,
       и сканер оставался ни с чем). */
    if (starting || running || stream) return;
    starting = true;
    wanted = true;
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showNoCamera('Браузер не даёт доступ к камере. Загрузите фото QR или введите номер.');
        return;
      }
      cam.hidden = false;
      toggle.textContent = 'Выключить камеру';
      say2('Включаем камеру…');
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false
        });
      } catch (error) {
        showNoCamera(cameraProblem(error));
        return;
      }

      /* Непрерывная фокусировка: без неё камера телефона часто не наводится
         на экран в упор. Браузеры, которые этого не умеют, просто не ответят. */
      var track = stream.getVideoTracks && stream.getVideoTracks()[0];
      if (track && track.applyConstraints) {
        try { await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (_) { /* не поддерживается */ }
      }

      video.srcObject = stream;
      var playing = true;
      try {
        await video.play();
      } catch (_) {
        /* Первая попытка могла не успеть за потоком — повторяем один раз. */
        try {
          await new Promise(function (done) { window.setTimeout(done, 250); });
          await video.play();
        } catch (_) { playing = false; }
      }

      /* Декодер готовим до проверки потока: если браузер не умеет читать QR,
         незачем держать включённой камеру. */
      var ok = await prepareDecoder();
      if (!ok) {
        showNoCamera('Этот браузер не умеет читать QR. Загрузите фото QR или введите номер.');
        return;
      }
      if (!playing) {
        /* Браузер не запускает картинку без касания (так делает iOS).
           Камеру отпускаем: следующее нажатие поднимет её уже из жеста. */
        showNoCamera('Нажмите «Включить камеру» — браузер ждёт касания.');
        return;
      }
      running = true;
      lastHit = Date.now();
      say2('Наведите на QR-код гостя');
      loop();
    } finally {
      starting = false;
    }
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
    say2(text);
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

  /* ── Фото QR: работает там, где камеры нет вовсе ────────────────────── */
  async function bitmapOf(fileObj) {
    if (window.createImageBitmap) {
      try { return await window.createImageBitmap(fileObj); } catch (_) { /* старый браузер */ }
    }
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(fileObj);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('Файл не открылся')); };
      img.src = url;
    });
  }

  if (file) {
    file.addEventListener('change', async function () {
      var chosen = file.files && file.files[0];
      file.value = '';
      if (!chosen) return;
      say2('Читаем фото…');
      try {
        await prepareDecoder();
        var bitmap = await bitmapOf(chosen);
        var width = bitmap.width || bitmap.naturalWidth;
        var height = bitmap.height || bitmap.naturalHeight;
        var text = null;
        /* Нативный детектор умеет и по картинке — пробуем его первым. */
        if (detector) {
          try {
            var found = await detector.detect(bitmap);
            if (found && found.length) text = found[0].rawValue;
          } catch (_) { /* ниже прочитает jsQR */ }
        }
        if (!text) text = decodeImage(bitmap, width, height, true);
        if (bitmap.close) bitmap.close();
        if (!text) {
          say2('На фото не нашёлся QR-код. Снимите ближе и ровнее.');
          return;
        }
        await onScanned(text);
      } catch (_) {
        say2('Фото не удалось прочитать. Попробуйте другое.');
      }
    });
  }

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
    lastHit = Date.now();
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
