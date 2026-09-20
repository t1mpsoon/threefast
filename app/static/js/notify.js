/* Уведомления «заказ готов»: работают, пока вкладка открыта (в фоне тоже). Без сервера и аккаунтов. */
(function () {
  'use strict';
  var supported = 'Notification' in window;
  var DISMISS = 'ep_notify_dismissed';

  function show(title, body, tag) {
    if (document.title.indexOf('•') !== 0 && document.hidden) document.title = '• ' + document.title;
    document.addEventListener('visibilitychange', function () {
      document.title = document.title.replace(/^• /, '');
    }, { once: true });
    if (!supported || Notification.permission !== 'granted') return;
    var opts = { body: body, tag: 'order-' + tag, icon: '/static/img/icon-192.png', badge: '/static/img/icon-192.png',
                 vibrate: [200, 100, 200], data: { url: location.href } };
    /* Android Chrome не умеет new Notification(): показываем через service worker. */
    if (navigator.serviceWorker && navigator.serviceWorker.ready) {
      navigator.serviceWorker.ready.then(function (reg) { return reg.showNotification(title, opts); })
        .catch(function () { try { new Notification(title, opts); } catch (_) {} });
    } else {
      try { new Notification(title, opts); } catch (_) {}
    }
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  }

  function ask(card) {
    if (!supported || Notification.permission !== 'default') return;
    try { if (sessionStorage.getItem(DISMISS)) return; } catch (_) {}
    var box = document.createElement('div');
    box.className = 'notify-ask';
    box.innerHTML =
      '<div class="notify-ask__text"><b>Сообщить, когда заказ будет готов?</b>' +
      '<span>Пришлём уведомление — можно не следить за экраном. Оставьте вкладку открытой.</span></div>' +
      '<button class="btn btn--sm" type="button" data-yes>Разрешить</button>' +
      '<button class="notify-ask__no" type="button" data-no aria-label="Не сейчас">×</button>';
    card.parentNode.insertBefore(box, card);
    box.querySelector('[data-yes]').addEventListener('click', function () {
      Notification.requestPermission().then(function (p) {
        box.remove();
        document.dispatchEvent(new CustomEvent('notify:resolved'));
        if (p === 'granted' && window.EP) EP.say('Готово: уведомим, когда заказ будет готов.', 'good');
      });
    });
    box.querySelector('[data-no]').addEventListener('click', function () {
      try { sessionStorage.setItem(DISMISS, '1'); localStorage.setItem('ep_notify_seen', '1'); } catch (_) {}
      box.remove();
      document.dispatchEvent(new CustomEvent('notify:resolved'));
    });
  }

  window.EPNotify = { show: show, ask: ask };
})();
