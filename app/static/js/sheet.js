/* Bottom sheet: выезжает снизу, закрывается свайпом вниз, крестиком и Escape. */
(function () {
  'use strict';

  var OPEN_CLASS = 'is-open';
  var CLOSE_DRAG = 0.28;   /* доля высоты, после которой шторка закрывается */

  /* Счётчик открытых шторок.

     Шторки открываются друг за другом: из табло времени гость уходит в
     оформление, а табло остаётся открытым под ним. Если каждая шторка будет
     сбрасывать body.overflow сама, то закрытие нижней вернёт прокрутку
     странице, на которой всё ещё висит верхняя. Поэтому блокировку прокрутки
     держим на счётчике: снимаем только когда закрылась последняя. */
  var openCount = 0;

  function lockScroll(sheetRoot) {
    openCount += 1;
    if (openCount === 1) {
      document.body.style.overflow = 'hidden';
      inertBackground(sheetRoot);
    }
  }

  function unlockScroll() {
    openCount = Math.max(openCount - 1, 0);
    if (openCount === 0) {
      document.body.style.overflow = '';
      releaseBackground();
    }
  }

  /* ── Фон под шторкой ────────────────────────────────────────────────────
     Пока шторка открыта, всё остальное на странице недоступно: атрибут inert
     убирает фон из обхода по Tab и из дерева доступности. Без него фокус
     уходил на ссылки за затемнением — при aria-modal="true" это тупик:
     скринридер фон не читает, а клавиатура в него попадает. */
  var inertNodes = [];

  function inertBackground(except) {
    if (inertNodes.length) return;
    Array.prototype.forEach.call(document.body.children, function (node) {
      if (node === except || node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
      /* Контейнер сообщений должен оставаться живым: туда летят подсказки. */
      if (node.id === 'notices') return;
      if (node.hasAttribute('inert')) return;
      node.setAttribute('inert', '');
      inertNodes.push(node);
    });
  }

  function releaseBackground() {
    inertNodes.forEach(function (node) { node.removeAttribute('inert'); });
    inertNodes = [];
  }

  function Sheet(rootId, scrimId) {
    this.root = document.getElementById(rootId);
    this.scrim = document.getElementById(scrimId);
    this.lastFocus = null;
    /* Шторка помнит, держит ли она блокировку: иначе двойное закрытие
       (свайп + Escape) уменьшило бы счётчик дважды. */
    this.locked = false;
    /* Открывается ли шторка прямо сейчас. */
    this.opened = false;
    if (!this.root) return;
    this.bind();
  }

  Sheet.prototype.bind = function () {
    var self = this;
    if (this.scrim) {
      this.scrim.addEventListener('click', function () { self.close(); });
    }
    this.root.querySelectorAll('[data-close]').forEach(function (button) {
      button.addEventListener('click', function () { self.close(); });
    });
    this.bindDrag();
  };

  /* Свайп вниз по ручке: на телефоне шторку закрывают именно так. */
  Sheet.prototype.bindDrag = function () {
    var self = this;
    var grip = this.root.querySelector('[data-drag]');
    if (!grip) return;
    var startY = 0;
    var delta = 0;
    var dragging = false;

    grip.addEventListener('pointerdown', function (event) {
      dragging = true;
      startY = event.clientY;
      delta = 0;
      self.root.classList.add('is-dragging');
      grip.setPointerCapture(event.pointerId);
    });

    grip.addEventListener('pointermove', function (event) {
      if (!dragging) return;
      delta = Math.max(event.clientY - startY, 0);
      self.root.style.transform = 'translateY(' + delta + 'px)';
    });

    function finish() {
      if (!dragging) return;
      dragging = false;
      self.root.classList.remove('is-dragging');
      self.root.style.transform = '';
      if (delta > self.root.offsetHeight * CLOSE_DRAG) self.close();
    }

    grip.addEventListener('pointerup', finish);
    grip.addEventListener('pointercancel', finish);
  };

  /* Состояние шторки держим в переменной, а не только в классе.

     Класс `is-open` ставится в следующем кадре — иначе не сработает transition.
     Значит между вызовом open() и следующим кадром шторка уже открывается, но
     по классу ещё «закрыта». Если опираться на класс, повторный open() в том же
     кадре пройдёт как новый и счётчик разъедется с реальностью. */
  Sheet.prototype.isOpen = function () {
    return Boolean(this.root && this.opened);
  };

  Sheet.prototype.open = function () {
    if (!this.root || this.opened) return;
    this.opened = true;
    /* Отменяем отложенное скрытие: иначе шторка, открытая в те же 300 мс
       после закрытия, тут же получала hidden и исчезала навсегда —
       вместе с ней пропадали и корзина, и прокрутка страницы. */
    if (this.hideTimer) {
      window.clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
    this.lastFocus = document.activeElement;
    if (this.scrim) this.scrim.hidden = false;
    this.root.hidden = false;
    /* Класс ставим в следующем кадре, иначе transition не сработает. */
    var self = this;
    window.requestAnimationFrame(function () {
      if (!self.opened) return;   /* за этот кадр шторку успели закрыть */
      if (self.scrim) self.scrim.classList.add(OPEN_CLASS);
      self.root.classList.add(OPEN_CLASS);
    });
    if (!this.locked) {
      lockScroll(this.root);
      this.locked = true;
    }
    /* Фокус уходит в шторку: гость сразу может работать с клавиатуры. */
    var focusable = this.root.querySelector('[data-close], input, button');
    if (focusable) window.setTimeout(function () {
      if (self.opened) focusable.focus();
    }, 300);
  };

  Sheet.prototype.close = function () {
    if (!this.root || !this.opened) return;
    this.opened = false;
    var self = this;
    this.root.classList.remove(OPEN_CLASS);
    if (this.scrim) this.scrim.classList.remove(OPEN_CLASS);
    /* Прокрутку возвращаем только когда закрылась последняя шторка. */
    if (this.locked) {
      unlockScroll();
      this.locked = false;
    }
    if (this.hideTimer) window.clearTimeout(this.hideTimer);
    this.hideTimer = window.setTimeout(function () {
      self.hideTimer = null;
      /* Если за это время шторку открыли снова — не прячем. */
      if (self.opened) return;
      self.root.hidden = true;
      if (self.scrim) self.scrim.hidden = true;
    }, 300);
    if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus();
  };

  /* Сколько шторок открыто сейчас — для проверок и отладки. */
  Sheet.openCount = function () { return openCount; };

  /* Видимые элементы, доступные с клавиатуры, по порядку обхода. */
  function focusableIn(root) {
    var selector = 'a[href], button:not([disabled]), input:not([disabled]), ' +
      'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.prototype.filter.call(root.querySelectorAll(selector), function (node) {
      if (node.hasAttribute('hidden') || node.closest('[hidden]')) return false;
      if (node.getAttribute('aria-hidden') === 'true') return false;
      var box = node.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    });
  }

  /* Верхняя открытая шторка: с ней и работаем. */
  function topSheet() {
    return window.EP_SHEETS.filter(function (sheet) { return sheet.opened; }).pop();
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      /* Закрываем только верхнюю шторку: раньше Escape схлопывал все сразу,
         и фокус улетал на кнопку под ними. */
      var open = topSheet();
      if (open) open.close();
      return;
    }
    if (event.key !== 'Tab') return;

    /* Замкнутый круг: фон помечен inert, поэтому выход за пределы шторки
       оставил бы фокус в никуда. */
    var current = topSheet();
    if (!current || !current.root) return;
    var items = focusableIn(current.root);
    if (!items.length) return;

    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;

    if (!current.root.contains(active)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  });

  window.EP_SHEETS = [
    new Sheet('time-sheet', 'time-scrim'),
    new Sheet('checkout-sheet', 'checkout-scrim')
  ];
  window.Sheet = Sheet;
})();
