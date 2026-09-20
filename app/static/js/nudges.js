/* Подсказки в нужный момент: как это работает, установка приложения, связь. Каждая — один раз, без навязчивости. */
(function () {
  'use strict';
  var D = window.EPDialog;
  if (!D) return;

  function get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }

  var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  var deferred = null;

  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); deferred = e; });
  window.addEventListener('appinstalled', function () {
    set('ep_installed', '1');
    if (window.EP && EP.say) EP.say('Приложение установлено. Ищите значок ThreeFast на экране.', 'good');
  });

  /* ── Установка приложения ───────────────────────────────────────────── */
  function canOfferInstall() {
    if (standalone || get('ep_installed')) return false;
    var t = Number(get('ep_install_later') || 0);
    if (t && Date.now() - t < 14 * 864e5) return false;   /* «Не сейчас» — молчим 2 недели */
    return Boolean(deferred) || isIOS;
  }

  function offerInstall() {
    if (!canOfferInstall() || D.isOpen()) return;
    var later = function () { set('ep_install_later', String(Date.now())); };
    if (deferred) {
      D.open({
        icon: '📲', title: 'Установите приложение',
        text: 'Заказ всегда под рукой: откроется с экрана телефона, без браузера и без ввода адреса.',
        actions: [
          { label: 'Установить', kind: 'primary', onClick: function () {
              deferred.prompt();
              deferred.userChoice.then(function (r) { if (r.outcome !== 'accepted') later(); deferred = null; });
          } },
          { label: 'Не сейчас', kind: 'ghost', onClick: later }
        ]
      });
    } else if (isIOS) {
      D.open({
        icon: '📲', title: 'Добавьте на экран «Домой»',
        text: 'Так заказ открывается одним касанием, как обычное приложение.',
        steps: ['Нажмите <b>«Поделиться»</b> внизу экрана Safari', 'Выберите <b>«На экран Домой»</b>', 'Нажмите <b>«Добавить»</b>'],
        actions: [{ label: 'Понятно', kind: 'primary', onClick: later }, { label: 'Не сейчас', kind: 'ghost', onClick: later }]
      });
    }
  }

  /* Кнопка «Установить» в шапке: доступна всегда, пока приложение не установлено. */
  function installNow() {
    if (deferred) {
      deferred.prompt();
      deferred.userChoice.then(function () { deferred = null; });
    } else if (isIOS) {
      D.open({
        icon: '📲', title: 'Добавьте на экран «Домой»',
        text: 'Так заказ открывается одним касанием, как обычное приложение.',
        steps: ['Нажмите <b>«Поделиться»</b> внизу экрана Safari', 'Выберите <b>«На экран Домой»</b>', 'Нажмите <b>«Добавить»</b>']
      });
    } else {
      D.open({
        icon: '📲', title: 'Установите приложение',
        text: 'Откройте меню браузера (три точки) и выберите «Установить приложение» или «Добавить на главный экран».'
      });
    }
  }

  var shift = document.getElementById('shift-toggle');
  if (shift && !standalone && !get('ep_installed')) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'install-btn';
    btn.setAttribute('aria-label', 'Установить приложение');
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
      '<path d="M12 3v12m0 0-4.5-4.5M12 15l4.5-4.5M5 19h14" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg><span>Установить</span>';
    btn.addEventListener('click', installNow);
    shift.parentNode.insertBefore(btn, shift);
    window.addEventListener('appinstalled', function () { btn.remove(); });
  }

  /* После оформления заказа: сперва разрешение на уведомления, потом установка. */
  var justOrdered = /[?&]fresh=1/.test(location.search) && location.pathname === '/order';
  if (justOrdered) {
    var fired = false;
    var go = function () { if (fired) return; fired = true; window.setTimeout(offerInstall, 900); };
    var pending = 'Notification' in window && Notification.permission === 'default' && !get('ep_notify_seen');
    if (pending) {
      document.addEventListener('notify:resolved', go, { once: true });
      window.setTimeout(go, 25000);
    } else {
      window.setTimeout(go, 2500);
    }
  }

  /* ── Как это работает: один раз на первом меню ──────────────────────── */
  if (/^\/e\/\d+\/menu/.test(location.pathname) && !get('ep_tour_seen')) {
    window.setTimeout(function () {
      if (D.isOpen()) return;
      D.open({
        icon: '🍽', title: 'Заказ за три шага',
        text: 'Без очереди и без регистрации.',
        steps: ['<b>Выберите блюда</b> — нажмите «+» на карточке', '<b>Выберите минуту</b> получения — вне часов пик дешевле', '<b>Назовите номер заказа</b> на выдаче — всё уже готово'],
        actions: [{ label: 'Начать', kind: 'primary', onClick: function () { set('ep_tour_seen', '1'); } }],
        onClose: function () { set('ep_tour_seen', '1'); }
      });
    }, 900);
  }

  /* ── Связь пропала / вернулась ──────────────────────────────────────── */
  window.addEventListener('offline', function () { if (window.EP && EP.say) EP.say('Нет соединения. Как только связь вернётся, всё обновится.', 'warn'); });
  window.addEventListener('online', function () { if (window.EP && EP.say) EP.say('Связь восстановлена.', 'good'); });
})();
