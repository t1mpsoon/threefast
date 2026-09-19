/* Шаг 1: меню заведения. Степпер с пружиной, плавающая панель, sticky-категории. */
(function () {
  'use strict';

  var placeId = window.PLACE_ID;
  var body = document.getElementById('menu-body');
  var cartbar = document.getElementById('cartbar');
  var cartCount = document.getElementById('cart-count');
  var cartSum = document.getElementById('cart-sum');
  var stickyHead = document.getElementById('sticky-head');
  var catsLane = document.getElementById('menu-cats');
  var note = document.getElementById('menu-note');

  var ADD_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';
  var MINUS_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M6 12h12" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>';
  var bound = Cart.bind(placeId);
  /* Заказ собирается в одном заведении. Если гость пришёл в другое, корзина
     очищается — и об этом нужно сказать, иначе выбор пропадает молча. */
  if (bound.dropped) {
    EP.say(
      'Заказ собирается в одном заведении, поэтому корзина очищена. ' +
      'Выбрано заново — уже здесь.',
      'warn',
      { title: 'Начинаем новый заказ' }
    );
  }

  /* ── Степпер: белая капсула с «+» превращается в «– 1 +» ───────────────── */

  function sideHtml(item, quantity) {
    if (quantity <= 0) {
      return '<button class="add-btn" type="button" data-act="more" aria-label="Добавить «' +
        EP.escapeHtml(item.name) + '»">' + ADD_ICON + '</button>';
    }
    return '<div class="stepper">' +
      '<button type="button" data-act="less" aria-label="Убрать порцию «' + EP.escapeHtml(item.name) + '»">' +
        MINUS_ICON + '</button>' +
      '<span class="stepper__n" aria-live="polite">' + quantity + '</span>' +
      '<button type="button" data-act="more" aria-label="Добавить порцию «' + EP.escapeHtml(item.name) + '»">' +
        ADD_ICON + '</button>' +
    '</div>';
  }

  function paintDish(id) {
    var row = body.querySelector('.dish[data-dish="' + id + '"]');
    if (!row) return;
    var item = {
      id: id,
      name: row.dataset.name,
      price: Number(row.dataset.price),
      cooks: Number(row.dataset.cooks)
    };
    var side = row.querySelector('.dish__side');
    side.innerHTML = sideHtml(item, Cart.quantityOf(id));
  }

  /* Мини-плашка «+1» всплывает над кнопкой и тает. */
  function showPlusOne(side) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var badge = document.createElement('span');
    badge.className = 'plus-one';
    badge.textContent = '+1';
    side.appendChild(badge);
    window.setTimeout(function () { badge.remove(); }, 900);
  }

  function spring(node) {
    if (!node || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    node.classList.remove('spring');
    void node.offsetWidth;
    node.classList.add('spring');
  }

  /* ── Полёт блюда в корзину ─────────────────────────────────────────────── */

  /* Копия фото летит от карточки к панели корзины и растворяется в ней.
     Это и есть «корзина плавно вылетает»: движение показывает, куда ушло блюдо. */
  function flyToCart(source, onDone) {
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || !cartbar || !source) {
      if (onDone) onDone();
      return;
    }
    var from = source.getBoundingClientRect();
    var to = (cartSum || cartbar).getBoundingClientRect();
    if (!from.width || !to.width) {
      if (onDone) onDone();
      return;
    }

    var ghost = document.createElement('span');
    ghost.className = 'fly';
    ghost.style.left = (from.left + from.width / 2 - 25) + 'px';
    ghost.style.top = (from.top + from.height / 2 - 25) + 'px';
    var source_img = source.tagName === 'IMG' ? source : source.querySelector('img');
    if (source_img) {
      var copy = document.createElement('img');
      copy.src = source_img.currentSrc || source_img.src;
      copy.alt = '';
      ghost.appendChild(copy);
    }
    document.body.appendChild(ghost);

    var shiftX = (to.left + to.width / 2) - (from.left + from.width / 2);
    var shiftY = (to.top + to.height / 2) - (from.top + from.height / 2);

    var flight = ghost.animate([
      { transform: 'translate(0, 0) scale(1)', opacity: 1 },
      { transform: 'translate(' + (shiftX * 0.55) + 'px,' + (shiftY * 0.35 - 40) +
                    'px) scale(0.72)', opacity: 1, offset: 0.55 },
      { transform: 'translate(' + shiftX + 'px,' + shiftY + 'px) scale(0.16)', opacity: 0.15 }
    ], { duration: 560, easing: 'cubic-bezier(0.34, 0.8, 0.4, 1)' });

    flight.onfinish = function () {
      ghost.remove();
      if (onDone) onDone();
    };
    flight.oncancel = function () {
      ghost.remove();
      if (onDone) onDone();
    };
  }

  /* ── Плавающая панель корзины: живой счётчик ───────────────────────────── */

  var shownSum = 0;

  function paintCartbar() {
    if (!cartbar) return;
    var count = Cart.portions();
    var total = Cart.sum();

    if (count === 0) {
      cartbar.classList.remove('is-up');
      cartbar.classList.add('is-down');
      shownSum = 0;
      /* Тексты обновляем и при пустой корзине: иначе в разметке остаётся
         «1 позиция» от прошлого заказа и путает при следующем открытии. */
      if (cartCount) cartCount.textContent = Cart.portionsLabel(0);
      if (cartSum) cartSum.textContent = EP.money(0);
      return;
    }

    var first = !cartbar.classList.contains('is-up');
    cartbar.classList.remove('is-down');
    cartbar.classList.add('is-up');

    /* Сумма прокручивается от старого значения, позиции дают короткий пульс. */
    EP.countUp(cartSum, shownSum, total, function (value) {
      return EP.money(value);
    }, 350);
    shownSum = total;

    cartCount.textContent = Cart.portionsLabel(count);
    if (!first) {
      EP.nudge(cartCount, 'pulse');
    }
  }

  function paintNote() {
    if (!note) return;
    var cooks = Cart.cooksFor();
    note.textContent = cooks
      ? 'Самое долгое блюдо готовится ' + cooks + ' мин — минуту выдачи предложим не раньше.'
      : '';
  }

  /* ── Sticky-шапка при скролле ──────────────────────────────────────────── */

  function paintStickyHead() {
    if (!stickyHead) return;
    var banner = document.querySelector('.banner');
    if (!banner) return;
    var passed = banner.getBoundingClientRect().bottom < 62;
    stickyHead.classList.toggle('is-shown', passed);
  }

  /* ── Синхронизация категорий со скроллом ───────────────────────────────── */

  function sections() {
    return Array.prototype.slice.call(document.querySelectorAll('.section'));
  }

  /* Плашка под активным чипом.

     Раньше её на этой странице не было, и активный чип оказывался белым
     текстом на белом фоне — то есть невидимым. */
  var catPill = null;
  function ensurePill() {
    if (!catsLane || catPill) return;
    catPill = document.createElement('span');
    catPill.className = 'chips__pill';
    catPill.setAttribute('aria-hidden', 'true');
    catPill.hidden = true;
    catsLane.insertBefore(catPill, catsLane.firstChild);
  }

  function setActiveChip(name) {
    if (!catsLane) return;
    ensurePill();
    var activeChip = null;
    catsLane.querySelectorAll('.chip').forEach(function (chip) {
      var active = chip.dataset.cat === name;
      chip.setAttribute('aria-pressed', active ? 'true' : 'false');
      if (active) {
        activeChip = chip;
        /* Держим активную капсулу в поле зрения ленты. */
        var lane = chip.parentElement;
        var target = chip.offsetLeft - lane.clientWidth / 2 + chip.offsetWidth / 2;
        lane.scrollTo({ left: Math.max(target, 0), behavior: 'smooth' });
      }
    });
    if (window.EP && EP.moveChipPill) EP.moveChipPill(catsLane, activeChip);
  }

  function paintActiveSection() {
    var list = sections();
    if (!list.length) return;
    var line = 150;   /* чуть ниже sticky-шапки */
    var current = list[0];
    list.forEach(function (section) {
      if (section.getBoundingClientRect().top <= line) current = section;
    });
    setActiveChip(current.dataset.section);
  }

  if (catsLane) {
    catsLane.addEventListener('click', function (event) {
      var chip = event.target.closest('.chip');
      if (!chip) return;
      var section = document.querySelector('.section[data-section="' + chip.dataset.cat + '"]');
      if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setActiveChip(chip.dataset.cat);
    });
  }

  /* ── Обработчики ───────────────────────────────────────────────────────── */

  if (body) {
    body.addEventListener('click', function (event) {
      var button = event.target.closest('button[data-act]');
      if (!button) return;
      var row = button.closest('.dish');
      var dish = {
        id: Number(row.dataset.dish),
        name: row.dataset.name,
        price: Number(row.dataset.price),
        cooks: Number(row.dataset.cooks)
      };
      var more = button.dataset.act === 'more';
      var result = Cart.add(dish, more ? 1 : -1);
      if (!result.ok) {
        EP.say(result.why, 'warn', { title: 'Столько не возьмём' });
        return;
      }
      var side = row.querySelector('.dish__side');
      paintDish(dish.id);
      if (more) {
        showPlusOne(side);
        spring(side.querySelector('.stepper'));
        /* Фото летит в панель: видно, куда ушло блюдо. */
        flyToCart(row.querySelector('.dish__photo'), null);
      }
    });
  }

  var cartOpen = document.getElementById('cart-open');
  if (cartOpen) {
    cartOpen.addEventListener('click', function () {
      if (Cart.portions() === 0) {
        EP.say('Сначала выберите блюдо.', 'warn');
        return;
      }
      if (window.TimeSheet) window.TimeSheet.open();
    });
  }

  document.addEventListener('cart:changed', function () {
    paintCartbar();
    paintNote();
  });

  /* ── Параллакс баннера заведения ───────────────────────────────────────── */

  /* Фото сдвигается медленнее страницы: тот же приём, что у промо на главной,
     только сдвиг считаем от положения баннера, а не от начала страницы. */
  var bannerPhoto = document.querySelector('.banner__photo');
  var banner = document.querySelector('.banner');
  var parallaxTicking = false;

  function paintBannerParallax() {
    if (!bannerPhoto || !banner) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var box = banner.getBoundingClientRect();
    /* Пока баннер на экране — сдвигаем; запас в 24px как раз на этот ход. */
    if (box.bottom < 0) return;
    var shift = Math.max(Math.min(-box.top * 0.12, 12), -12);
    bannerPhoto.style.transform = 'translateY(' + shift.toFixed(2) + 'px)';
  }

  /* Поворот экрана и смена размера шрифта меняют ширину чипов —
     плашку под активным двигаем заново. */
  window.addEventListener('resize', function () {
    if (!catsLane) return;
    EP.moveChipPill(catsLane, catsLane.querySelector('.chip[aria-pressed="true"]'));
  });

  window.addEventListener('scroll', function () {
    paintStickyHead();
    paintActiveSection();
    if (parallaxTicking) return;
    parallaxTicking = true;
    window.requestAnimationFrame(function () {
      paintBannerParallax();
      parallaxTicking = false;
    });
  }, { passive: true });

  document.querySelectorAll('.dish').forEach(function (row) {
    paintDish(Number(row.dataset.dish));
  });

  /* Карточки блюд появляются волной сверху вниз. */
  EP.stagger(document.querySelectorAll('.dish'), { step: 40, base: 60 });

  paintCartbar();
  paintNote();
  paintStickyHead();
  paintActiveSection();
  paintBannerParallax();
})();
