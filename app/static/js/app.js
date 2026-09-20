/* Общее для всех экранов: запросы, деньги, время, смена оформления. */
(function () {
  'use strict';

  var TIMEOUT = 15000;

  /* ── Запросы ───────────────────────────────────────────────────────────── */

  function ApiError(message, status, code, payload) {
    this.name = 'ApiError';
    this.message = message;
    this.status = status || 0;
    this.code = code || 'error';
    this.payload = payload || {};
  }
  ApiError.prototype = Object.create(Error.prototype);

  async function apiFetch(url, options) {
    var config = Object.assign({ headers: {} }, options || {});
    if (config.body && !config.headers['Content-Type']) {
      config.headers['Content-Type'] = 'application/json';
    }
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, TIMEOUT);
    config.signal = controller.signal;

    var response;
    try {
      response = await fetch(url, config);
    } catch (error) {
      clearTimeout(timer);
      if (error && error.name === 'AbortError') {
        throw new ApiError('Сервер не ответил за 15 секунд. Нажмите ещё раз — заказ не потеряется.', 0, 'timeout');
      }
      throw new ApiError('Связь пропала. Проверьте интернет и нажмите ещё раз.', 0, 'network');
    }
    clearTimeout(timer);

    if (response.status === 204) return null;

    var text = await response.text();
    var payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch (_) { payload = { detail: text }; }
    }
    if (!response.ok) {
      throw new ApiError(
        (payload && (payload.detail || payload.message)) || 'Не получилось. Попробуйте ещё раз.',
        response.status,
        (payload && payload.code) || 'error',
        payload
      );
    }
    return payload;
  }

  /* ── Сообщения ─────────────────────────────────────────────────────────── */

  function say(message, kind, options) {
    var host = document.getElementById('notices');
    var opts = options || {};
    if (!host) { window.alert(message); return null; }
    var box = document.createElement('div');
    box.className = 'note note--' + (kind || 'info');
    box.setAttribute('role', kind === 'bad' ? 'alert' : 'status');
    if (opts.title) {
      var strong = document.createElement('strong');
      strong.textContent = opts.title;
      box.appendChild(strong);
    }
    box.appendChild(document.createTextNode(message));
    host.appendChild(box);
    placeNotices();
    if (!opts.sticky) setTimeout(function () { box.remove(); }, 9000);
    return box;
  }

  function clearNotices() {
    var host = document.getElementById('notices');
    if (host) host.textContent = '';
  }

  /* Сообщения не должны залезать под шапку: на телефоне она выше. */
  function placeNotices() {
    var host = document.getElementById('notices');
    var top = document.querySelector('.top');
    if (!host || !top) return;
    if (getComputedStyle(top).position !== 'sticky') return;
    host.style.top = Math.round(top.getBoundingClientRect().bottom + 12) + 'px';
  }

  /* ── Числа и время ─────────────────────────────────────────────────────── */

  /* Суммы всегда с разрядом: 2 200 ₸, а не 2200. Неразрывный пробел, чтобы
     разряд не переносился на другую строку. */
  function money(value) {
    var n = Number(value || 0);
    var hasKopecks = Math.round(n * 100) % 100 !== 0;
    var text = n.toLocaleString('ru-RU', {
      minimumFractionDigits: hasKopecks ? 2 : 0,
      maximumFractionDigits: 2
    });
    return text.replace(/\u00A0/g, '\u2009') + ' ₸';
  }


  /* Русское склонение по числу: 1 позиция, 2 позиции, 5 позиций.
     Одна реализация на весь проект — раньше копии расползались по файлам
     и однажды потерялись вместе с очисткой кода. */
  function plural(n, one, few, many) {
    var tail = Math.abs(n) % 100;
    if (tail >= 11 && tail <= 14) return many;
    var last = tail % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  /* Число-одометр: прокручивает значение от старого к новому. */
  function countUp(node, from, to, format, duration) {
    if (!node) return;
    var span = (duration || 350);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || from === to) {
      node.textContent = format(to);
      return;
    }
    var start = null;
    function step(timestamp) {
      if (start === null) start = timestamp;
      var share = Math.min((timestamp - start) / span, 1);
      /* Плавный разгон и торможение — та же кривая, что у заполнения. */
      var eased = share < 0.5 ? 2 * share * share : 1 - Math.pow(-2 * share + 2, 2) / 2;
      node.textContent = format(Math.round(from + (to - from) * eased));
      if (share < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  /* Короткий импульс элемента: класс снимается, чтобы анимация повторялась. */
  function nudge(node, className) {
    if (!node || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    node.classList.remove(className);
    void node.offsetWidth;
    node.classList.add(className);
    window.setTimeout(function () { node.classList.remove(className); }, 400);
  }

  /* Последовательное появление: экран «собирается», а не рендерится разом. */
  function stagger(nodes, options) {
    var opts = options || {};
    var step = opts.step || 50;
    var base = opts.base || 0;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    Array.prototype.forEach.call(nodes, function (node, index) {
      node.classList.add(opts.className || 'enter');
      node.style.animationDelay = (base + index * step) + 'ms';
    });
  }

  function timeOf(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  function whenOf(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    var today = new Date();
    var tomorrow = new Date(today.getTime() + 86400000);
    if (d.toDateString() === today.toDateString()) return 'сегодня в ' + timeOf(iso);
    if (d.toDateString() === tomorrow.toDateString()) return 'завтра в ' + timeOf(iso);
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) + ' в ' + timeOf(iso);
  }

  function secondsLeft(iso) {
    return Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  }

  function countdown(seconds) {
    var late = seconds < 0;
    var total = Math.abs(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var body = (h > 0 ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
    return (late ? '−' : '') + body;
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ── Поля формы ────────────────────────────────────────────────────────── */

  function badField(inputId, message) {
    var input = document.getElementById(inputId);
    if (!input) return;
    var field = input.closest('.field');
    if (!field) return;
    var box = field.querySelector('.field__error');
    if (message) {
      field.classList.add('is-bad');
      if (box) {
        box.textContent = message;
        /* Скринридер должен услышать не только «поле неверно», но и почему:
           без связи через aria-describedby текст ошибки для него не существует. */
        if (!box.id) box.id = inputId + '-error';
        input.setAttribute('aria-describedby', box.id);
      }
      input.setAttribute('aria-invalid', 'true');
    } else {
      field.classList.remove('is-bad');
      if (box) box.textContent = '';
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    }
  }

  function cleanFields(scope) {
    if (!scope) return;
    scope.querySelectorAll('.field.is-bad').forEach(function (field) {
      field.classList.remove('is-bad');
      var box = field.querySelector('.field__error');
      if (box) box.textContent = '';
      var input = field.querySelector('input, textarea, select');
      if (input) {
        input.removeAttribute('aria-invalid');
        input.removeAttribute('aria-describedby');
      }
    });
  }

  /* Первое плохое поле получает фокус: гость сразу видит, что исправить. */
  function focusFirstBad(scope) {
    if (!scope) return;
    var bad = scope.querySelector('.field.is-bad input, .field.is-bad textarea, .field.is-bad select');
    if (bad) bad.focus();
  }

  function busy(button, label, task) {
    var start = button.innerHTML;
    var wasDisabled = button.disabled;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    if (label) button.textContent = label;
    return Promise.resolve().then(task).finally(function () {
      button.disabled = wasDisabled;
      button.removeAttribute('aria-busy');
      button.innerHTML = start;
    });
  }

  /* ── Смена оформления ──────────────────────────────────────────────────── */

  function currentShift() {
    var set = document.documentElement.getAttribute('data-theme');
    if (set) return set;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function shiftName(shift) { return shift === 'dark' ? 'Тёмная' : 'Светлая'; }

  function paintShiftButton() {
    var buttons = document.querySelectorAll('.shift-toggle');
    if (!buttons.length) return;
    var now = currentShift();
    var next = now === 'dark' ? 'light' : 'dark';
    buttons.forEach(function (button) {
      button.setAttribute('title', 'Сейчас: ' + shiftName(now).toLowerCase());
      button.setAttribute('aria-label', 'Оформление: ' + shiftName(now).toLowerCase() +
        '. Переключить на ' + shiftName(next).toLowerCase() + '.');
      button.setAttribute('aria-pressed', now === 'dark' ? 'true' : 'false');
    });
  }

  /* Оформление меняется плавно: короткая волна по экрану, если браузер умеет. */
  function applyShift(next) {
    var root = document.documentElement;
    var change = function () { root.setAttribute('data-theme', next); };
    if (document.startViewTransition &&
        !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      document.startViewTransition(change);
    } else {
      change();
    }
    try { localStorage.setItem('ep-shift', next); } catch (_) { /* приватный режим */ }
    paintShiftButton();
  }

  /* ── Нижняя навигация ──────────────────────────────────────────────────── */

  /* Плашка-индикатор встаёт под активную вкладку при загрузке и едет при клике. */
  function moveTabbarPill() {
    var bar = document.querySelector('.tabbar');
    var pill = document.getElementById('tabbar-pill');
    var active = document.querySelector('.tabbar__tab[aria-current="page"]');
    if (!bar || !pill || !active) return;
    /* Пока элемент скрыт (широкий экран), размеров нет — молча выходим. */
    if (!active.offsetWidth) return;
    /* Полоса занимает треть вкладки: в навигации три ссылки и переключатель темы. */
    var share = 1 / 3;
    pill.style.width = Math.round(active.offsetWidth * share) + 'px';
    pill.style.transform = 'translateX(' +
      Math.round(active.offsetLeft + active.offsetWidth * (1 - share) / 2) + 'px)';
  }

  /* ── Плашка под активным чипом ─────────────────────────────────────────── */

  /* Плашка едет под выбранный чип. Без неё активный чип полагается только на
     белый текст — на белом фоне его не видно вовсе. */
  function moveChipPill(container, active) {
    if (!container) return;
    var pill = container.querySelector('.chips__pill');
    if (!pill) return;
    if (!active || !active.offsetWidth) {
      pill.hidden = true;
      return;
    }
    pill.hidden = false;
    var box = container.getBoundingClientRect();
    var target = active.getBoundingClientRect();
    pill.style.width = Math.round(target.width) + 'px';
    pill.style.height = Math.round(target.height) + 'px';
    /* Плашка абсолютная: её начало совпадает с левым краем прокручиваемой
       области, поэтому позицию даёт смещение чипа плюс прокрутка ленты.
       Явный top снимает прежний сдвиг вверх — плашка стояла над подписью. */
    pill.style.top = (parseFloat(getComputedStyle(container).paddingTop) || 0) + 'px';
    pill.style.transform = 'translateX(' +
      Math.round(target.left - box.left + container.scrollLeft) + 'px)';
  }

  /* ── Возврат к началу страницы ─────────────────────────────────────────── */

  /* Кнопка появляется после того, как гость прокрутил экран, и возвращает
     наверх. На длинных экранах — очередь кухни, меню — это экономит
     десяток свайпов. */
  function bindToTop() {
    var button = document.getElementById('to-top');
    if (!button) return;
    var SHOW_AFTER = 420;
    var shown = false;

    button.addEventListener('click', function () {
      var smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' });
      /* Возвращаем фокус на начало: так удобнее и с клавиатуры. */
      var skip = document.querySelector('.skip-link, .brand');
      if (skip && skip.focus) skip.focus({ preventScroll: true });
    });

    function paint() {
      var need = window.scrollY > SHOW_AFTER;
      if (need === shown) return;
      shown = need;
      button.hidden = !need;
      button.classList.toggle('is-on', need);
    }

    window.addEventListener('scroll', paint, { passive: true });
    window.addEventListener('resize', paint);
    paint();
  }

  /* ── Плавные переходы по кнопкам ───────────────────────────────────────── */

  /* Переход на другой экран: старая страница уезжает, новая приходит.
     Одна точка входа для скриптов, чтобы все переходы выглядели одинаково. */
  function go(url) {
    if (!document.startViewTransition ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.location.href = url;
      return;
    }
    document.startViewTransition(function () { window.location.href = url; });
  }

  /* Любая внутренняя ссылка и кнопка-ссылка ведут на новый экран мягко. */
  function bindLinkTransitions() {
    if (!document.startViewTransition) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    document.addEventListener('click', function (event) {
      if (event.defaultPrevented) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (event.button !== 0) return;

      var link = event.target.closest('a[href]');
      if (!link) return;
      if (link.target && link.target !== '_self') return;
      if (link.hasAttribute('download') || link.dataset.noTransition) return;

      var href = link.getAttribute('href');
      /* Только внутренние адреса и только не текущий: якоря и внешние ссылки
         должны работать как обычно. */
      if (!href || href.charAt(0) !== '/' || href.charAt(1) === '/') return;
      if (href.indexOf('#') === 0) return;
      if (link.hasAttribute('aria-current')) return;
      var here = window.location.pathname + window.location.search;
      if (href === here) {
        event.preventDefault();
        return;
      }

      event.preventDefault();
      go(href);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    placeNotices();
    paintShiftButton();
    moveTabbarPill();
    bindLinkTransitions();
    /* Переключателей два: в шапке и в нижней полосе. Слушаем оба. */
    document.querySelectorAll('.shift-toggle').forEach(function (button) {
      button.addEventListener('click', function () {
        applyShift(currentShift() === 'dark' ? 'light' : 'dark');
      });
    });
  });
  window.addEventListener('resize', function () {
    placeNotices();
    moveTabbarPill();
  });
  window.addEventListener('load', moveTabbarPill);
  bindToTop();

  /* ── Выход из смены ────────────────────────────────────────────────────── */

  async function logout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (_) { /* даже если связи нет, уходим на вход: cookie гасит сервер */ }
    go('/login');
  }

  /* Кнопка выхода живёт в шапке всех страниц, поэтому обработчик общий. */
  var logoutButton = document.getElementById('logout-button');
  if (logoutButton) {
    logoutButton.addEventListener('click', function () {
      busy(logoutButton, 'Выходим', logout);
    });
  }

  window.EP = {
    apiFetch: apiFetch,
    ApiError: ApiError,
    say: say,
    clearNotices: clearNotices,
    placeNotices: placeNotices,
    money: money,
    plural: plural,
    countUp: countUp,
    go: go,
    logout: logout,
    nudge: nudge,
    stagger: stagger,
    moveTabbarPill: moveTabbarPill,
    moveChipPill: moveChipPill,
    timeOf: timeOf,
    whenOf: whenOf,
    secondsLeft: secondsLeft,
    countdown: countdown,
    escapeHtml: escapeHtml,
    badField: badField,
    cleanFields: cleanFields,
    focusFirstBad: focusFirstBad,
    busy: busy
  };
})();
