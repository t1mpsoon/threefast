/* Главная: сводка, витрина блюд, список заведений, фильтр по кухням.
   Данные приходят одним запросом /api/establishments/home. */
(function () {
  'use strict';

  var host = document.getElementById('places');
  var chips = document.getElementById('cuisine-chips');
  var searchInput = document.getElementById('place-search');
  var clearButton = document.getElementById('search-clear');
  var note = document.getElementById('places-note');
  var popularBlock = document.getElementById('popular-block');
  var popularRail = document.getElementById('popular-rail');
  var placesCount = document.getElementById('places-count');
  var clock = document.getElementById('live-clock');
  var windowCard = document.getElementById('window-card');

  /* Состояние экрана: данные приходят одним запросом. */
  var all = [];
  var popular = [];
  var cuisine = '';

  /* Звезда рейтинга: тот же набор иконок, что и везде. */
  var STAR = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M12 2.8l2.9 5.9 6.5.95-4.7 4.6 1.1 6.45L12 17.65 6.2 20.7l1.1-6.45-4.7-4.6 ' +
    '6.5-.95L12 2.8Z" fill="currentColor"/></svg>';

  /* ── Бейджи: одна форма, три состояния, всегда низ-лево ────────────────── */

  function badges(item) {
    var items = [];
    if (item.load === 'closed') {
      items.push('<span class="badge badge--closed">' + EP.escapeHtml(item.load_label) + '</span>');
    } else {
      var kind = item.load === 'free' ? 'free' : (item.load === 'busy' ? 'busy' : 'packed');
      items.push('<span class="badge badge--' + kind + '">' +
        EP.escapeHtml(item.load_label) + '</span>');
      if (item.ready_in_minutes !== null) {
        items.push('<span class="badge badge--time">Заберёте за ' + item.ready_in_minutes + ' мин</span>');
      }
    }
    return '<span class="place__badges">' + items.join('') + '</span>';
  }

  function rating(item) {
    return '<span class="place__rating">' + STAR + EP.escapeHtml(item.rating.toFixed(1)) + '</span>';
  }

  function meta(item) {
    return EP.escapeHtml(item.cuisine || 'Кафе') +
      (item.address ? ' · ' + EP.escapeHtml(item.address) : '') +
      ' · работает ' + EP.escapeHtml(item.opens_at) + '–' + EP.escapeHtml(item.closes_at);
  }

  /* Все заведения — одинаковыми карточками: ни одна не занимает больше места.
     Самое быстрое отмечаем бейджем, а не размером. */
  function card(item, fastest) {
    return '<a class="place" href="/e/' + item.id + '/menu"' +
      (fastest ? ' data-fastest="1"' : '') + '>' +
      '<span class="place__media">' +
        '<img class="place__photo" src="' + EP.escapeHtml(item.photo || '') + '"' +
        ' alt="" loading="lazy" width="640" height="400">' +
        (fastest ? '<span class="place__flag">Быстрее всего</span>' : '') +
        badges(item) +
      '</span>' +
      '<span class="place__body">' +
        '<span class="place__line">' +
          '<span class="place__name">' + EP.escapeHtml(item.name) + '</span>' +
          rating(item) +
        '</span>' +
        '<span class="place__meta">' + meta(item) + '</span>' +
      '</span>' +
    '</a>';
  }

  /* ── Ближайшее окно: живой отсчёт до самой ранней минуты ───────────────── */

  var windowTarget = null;
  var RING_LENGTH = 2 * Math.PI * 30;

  function paintWindowCard(fastest) {
    if (!windowCard) return;
    if (!fastest) {
      /* Заведения закрыты: показываем, когда откроется ближайшее. */
      if (!windowTarget) {
        windowCard.hidden = true;
        return;
      }
    }
    windowCard.hidden = false;
    windowCard.innerHTML =
      '<div class="window-card__ring">' +
        '<svg viewBox="0 0 68 68" aria-hidden="true">' +
          '<circle class="window-card__track" cx="34" cy="34" r="30"/>' +
          '<circle class="window-card__arc" cx="34" cy="34" r="30" ' +
            'stroke-dasharray="' + RING_LENGTH.toFixed(1) + '" ' +
            'stroke-dashoffset="' + RING_LENGTH.toFixed(1) + '" id="window-arc"/>' +
        '</svg>' +
        '<span class="window-card__digit" id="window-count">--:--</span>' +
      '</div>' +
      '<div class="window-card__body">' +
        '<div class="window-card__title">Ближайшее окно выдачи</div>' +
        '<div class="window-card__note" id="window-note"></div>' +
      '</div>' +
      '<a class="btn btn--flame window-card__cta" href="#places">Выбрать заведение</a>';
  }

  function tickWindow() {
    if (!windowCard || windowCard.hidden || !windowTarget) return;
    var left = Math.max(Math.round((windowTarget - Date.now()) / 1000), 0);
    var minutes = Math.floor(left / 60);
    var seconds = left % 60;
    var count = document.getElementById('window-count');
    var note = document.getElementById('window-note');
    var arc = document.getElementById('window-arc');
    if (count) {
      count.textContent = minutes + ':' + String(seconds).padStart(2, '0');
    }
    /* Кольцо заполняется по мере приближения окна: нагляднее числа. */
    if (arc) {
      var share = Math.min(Math.max(1 - left / (30 * 60), 0.06), 1);
      arc.setAttribute('stroke-dashoffset', (RING_LENGTH * (1 - share)).toFixed(1));
    }
    if (note && !note.dataset.filled) {
      note.textContent = 'Свободная минута уже есть — заказ приготовят к этому времени.';
      note.dataset.filled = '1';
    }
    if (left === 0 && note) {
      note.textContent = 'Минута наступила — выберите следующую на табло.';
    }
  }

  /* ── Появление блоков при скролле ──────────────────────────────────────── */

  function bindReveal() {
    var nodes = document.querySelectorAll('.reveal:not(.is-in):not([data-revealing])');
    if (!nodes.length) return;
    nodes.forEach(function (node) { node.dataset.revealing = '1'; });

    if (!('IntersectionObserver' in window) ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      nodes.forEach(function (node) {
        node.classList.add('is-in');
      });
      return;
    }
    var observer = revealObserver();
    nodes.forEach(function (node) { observer.observe(node); });
  }

  var _revealObserver = null;
  function revealObserver() {
    if (_revealObserver) return _revealObserver;
    _revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        _revealObserver.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px 10% 0px', threshold: 0 });
    return _revealObserver;
  }

  /* ── Баннер: несколько слайдов со сменой по кругу ──────────────────────── */

  var SLIDE_MS = 6500;

  function slideMarkup(slide) {
    return '<div class="promo__slide">' +
      '<img class="promo__photo" src="' + EP.escapeHtml(slide.photo) + '" alt="" ' +
        'width="1120" height="400" loading="lazy" aria-hidden="true">' +
      '<span class="promo__tint"></span>' +
      '<span class="promo__veil"></span>' +
      '<div class="promo__text">' +
        '<div class="promo__title">' + EP.escapeHtml(slide.title) + '</div>' +
        '<div class="promo__note">' + EP.escapeHtml(slide.note) + '</div>' +
      '</div>' +
      '<span class="promo__badge">' + EP.escapeHtml(slide.badge) + '</span>' +
    '</div>';
  }

  /* Слайды не выдуманные: каждый показывает факт из данных витрины. */
  function buildSlides(stats, places, dishes) {
    var slides = [];
    var photoOf = function (item) {
      return (item && item.photo) || '/static/img/places/central.jpg';
    };

    if (stats.fastest_ready_minutes) {
      var quickest = places.filter(function (p) { return p.ready_in_minutes !== null; })[0];
      slides.push({
        title: 'Обед без ожидания',
        note: 'Сейчас быстрее всего — ' + (quickest ? quickest.name : 'рядом') +
              '. Готовим к названной минуте, без очереди на кассе.',
        badge: 'Готовим за ' + stats.fastest_ready_minutes + ' мин',
        photo: photoOf(quickest)
      });
    } else {
      slides.push({
        title: 'Обед без ожидания',
        note: 'Заказывайте заранее и забирайте к названной минуте — без очереди на кассе.',
        badge: stats.opens_at ? 'Откроется в ' + stats.opens_at : 'Заказ на завтра',
        photo: photoOf(places[0])
      });
    }

    if (dishes.length) {
      var popularDish = dishes[0];
      slides.push({
        title: 'Берут чаще всего',
        note: popularDish.name + (popularDish.place_names.length > 1
          ? ' — есть в ' + popularDish.place_names.length + ' заведениях поблизости.'
          : ' — из меню «' + (popularDish.place_names[0] || '') + '».'),
        badge: 'от ' + EP.money(popularDish.price),
        photo: photoOf(popularDish)
      });
    }

    var openPlace = places.filter(function (p) { return p.is_open_now; })[0];
    if (openPlace && openPlace.nearest_slot) {
      var at = new Date(openPlace.nearest_slot);
      slides.push({
        title: 'Свободная минута уже есть',
        note: 'Табло показывает, сколько порций кухня успевает приготовить. ' +
              'Занимайте минуту — остальное сделаем мы.',
        badge: openPlace.name + ' · ' +
          String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0'),
        photo: photoOf(openPlace)
      });
    } else if (places.length) {
      var last = places[places.length - 1];
      slides.push({
        title: 'Кухня берёт столько, сколько успевает',
        note: 'Поэтому заказ всегда готов к вашей минуте: ' + last.name +
              ' и другие точки рядом.',
        badge: stats.dishes_count + ' блюд в меню',
        photo: photoOf(last)
      });
    }

    return slides.slice(0, 3);
  }

  var slides = [];
  var slideIndex = 0;
  var slideTimer = null;
  var slidesHost = document.getElementById('promo-slides');
  var dotsHost = document.getElementById('promo-dots');

  function showSlide(index) {
    if (!slides.length || !slidesHost) return;
    slideIndex = (index + slides.length) % slides.length;
    slidesHost.querySelectorAll('.promo__slide').forEach(function (node, i) {
      node.classList.toggle('is-on', i === slideIndex);
      node.classList.toggle('is-out', i < slideIndex);
    });
    if (dotsHost) {
      dotsHost.querySelectorAll('.promo__dot').forEach(function (dot, i) {
        dot.classList.toggle('is-on', i === slideIndex);
        dot.setAttribute('aria-selected', i === slideIndex ? 'true' : 'false');
      });
    }
    restartTimer();
  }

  /* Полоса отсчёта перезапускается вместе со слайдом. */
  function restartTimer() {
    if (slideTimer) window.clearInterval(slideTimer);
    if (slides.length < 2) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    slideTimer = window.setInterval(function () {
      if (document.hidden) return;
      showSlide(slideIndex + 1);
    }, SLIDE_MS);
  }

  function paintSlides(list) {
    if (!slidesHost || !list.length) return;
    slides = list;
    slidesHost.innerHTML = list.map(slideMarkup).join('');
    slidesHost.insertAdjacentHTML('beforeend',
      '<span class="promo__progress"><span></span></span>');
    if (dotsHost) {
      dotsHost.hidden = list.length < 2;
      dotsHost.innerHTML = list.map(function (slide, index) {
        return '<button class="promo__dot" type="button" role="tab" data-slide="' + index +
          '" aria-label="Баннер ' + (index + 1) + ': ' + EP.escapeHtml(slide.title) + '"></button>';
      }).join('');
      dotsHost.addEventListener('click', function (event) {
        var dot = event.target.closest('.promo__dot');
        if (!dot) return;
        showSlide(Number(dot.dataset.slide));
      });
    }
    showSlide(0);
    bindSlideSwipe();
  }

  /* Свайп по баннеру: влево — следующий, вправо — предыдущий. */
  function bindSlideSwipe() {
    var promo = document.getElementById('promo');
    if (!promo || slides.length < 2) return;
    var startX = null;
    promo.addEventListener('touchstart', function (event) {
      startX = event.touches[0].clientX;
    }, { passive: true });
    promo.addEventListener('touchend', function (event) {
      if (startX === null) return;
      var shift = event.changedTouches[0].clientX - startX;
      startX = null;
      if (Math.abs(shift) < 40) return;
      showSlide(slideIndex + (shift < 0 ? 1 : -1));
    }, { passive: true });
  }

  /* «в 2 заведениях», «в 1 заведении» — падеж зависит от числа. */
  function placesWord(n) {
    return n === 1 ? 'заведении' : 'заведениях';
  }

  /* ── Витрина популярных блюд ───────────────────────────────────────────── */

  function paintPopular() {
    if (!popularRail || !popularBlock) return;
    if (!popular.length) {
      popularBlock.hidden = true;
      return;
    }
    popularBlock.hidden = false;
    popularRail.innerHTML = popular.map(function (dish) {
      var where = dish.places_count > 1
        ? 'в ' + dish.places_count + ' ' + placesWord(dish.places_count)
        : EP.escapeHtml(dish.place_names[0] || '');      return '<a class="popular" href="#places">' +
        '<span class="popular__media">' +
          '<img class="popular__photo" src="' + EP.escapeHtml(dish.photo || '') + '"' +
          ' alt="" loading="lazy" width="400" height="300">' +
          '<span class="popular__where"><span class="badge badge--glass">' + where + '</span></span>' +
        '</span>' +
        '<span class="popular__body">' +
          '<span class="popular__name">' + EP.escapeHtml(dish.name) + '</span>' +
          '<span class="popular__places">' +
            EP.escapeHtml((dish.place_names || []).join(', ')) + '</span>' +
          '<span class="popular__row">' +
            '<span class="popular__price">от ' + EP.money(dish.price) + '</span>' +
            '<span class="popular__time">' + dish.prep_time_minutes + ' мин</span>' +
          '</span>' +
        '</span>' +
      '</a>';
    }).join('');
    EP.stagger(popularRail.querySelectorAll('.popular'), { step: 45, base: 40 });
  }

  /* ── Список заведений ──────────────────────────────────────────────────── */

  /* Поиск ищет по названию, улице, кухне и блюдам: гость часто помнит еду,
     а не вывеску. */
  function searchIndex() {
    if (searchIndex.cache && searchIndex.cache.length === all.length) return searchIndex.cache;
    searchIndex.cache = all.map(function (item) {
      return (item.name + ' ' + (item.address || '') + ' ' + (item.cuisine || '') + ' ' +
        (item.popular_dishes || []).join(' ')).toLowerCase();
    });
    return searchIndex.cache;
  }

  function visible() {
    var needle = (searchInput.value || '').trim().toLowerCase();
    var index = searchIndex();
    return all.filter(function (item, position) {
      if (cuisine && (item.cuisine || '') !== cuisine) return false;
      if (!needle) return true;
      return index[position].indexOf(needle) !== -1;
    });
  }

  function nothingFound() {
    var hint = (searchInput.value || '').trim()
      ? 'По запросу «' + EP.escapeHtml(searchInput.value.trim()) + '» ничего не нашлось. ' +
        'Попробуйте другое блюдо, кухню или улицу.'
      : 'Попробуйте другой район или снимите фильтр по кухне.';
    return '<div class="empty" style="grid-column:1/-1">' +
      '<svg class="void-art" viewBox="0 0 120 120" fill="none" aria-hidden="true">' +
        '<circle cx="52" cy="50" r="26" stroke-width="4"/>' +
        '<path d="M52 36v16l11 7" class="void-art__accent" stroke-width="4" stroke-linecap="round"/>' +
        '<path d="m71 69 18 18" stroke-width="5" stroke-linecap="round"/>' +
        '<path d="M18 98h34M18 108h56" stroke-width="4" stroke-linecap="round"/>' +
      '</svg>' +
      '<h3>Ничего не нашли рядом</h3>' +
      '<p>' + hint + '</p>' +
      '<button class="btn btn--flame" type="button" id="void-reset" style="margin-top:14px">' +
      'Показать все заведения</button></div>';
  }

  function paint() {
    var list = visible();
    if (placesCount) {
      placesCount.textContent = list.length
        ? list.length + ' ' + EP.plural(list.length, 'заведение', 'заведения', 'заведений')
        : '';
    }
    if (clearButton) clearButton.hidden = !(searchInput.value || '').trim();

    if (!list.length) {
      host.innerHTML = nothingFound();
      note.textContent = '';
      var reset = document.getElementById('void-reset');
      if (reset) {
        reset.addEventListener('click', function () {
          searchInput.value = '';
          cuisine = '';
          chips.querySelectorAll('.chip').forEach(function (node) {
            node.setAttribute('aria-pressed', node.dataset.cuisine === '' ? 'true' : 'false');
          });
          movePill(chips.querySelector('.chip[aria-pressed="true"]'));
          paint();
        });
      }
      return;
    }

    /* Все карточки одинаковые. Самое быстрое заведение просто помечено. */
    var fastest = list.filter(function (i) { return i.ready_in_minutes !== null; })[0];
    host.innerHTML = list.map(function (item) {
      return card(item, item === fastest);
    }).join('');
    EP.stagger(host.querySelectorAll('.place'), { step: 50, base: 60 });

    note.textContent = fastest
      ? 'Быстрее всего сейчас: ' + fastest.name + ' — заберёте через ' +
        fastest.ready_in_minutes + ' мин.'
      : 'Сейчас все заведения закрыты — заказ можно оформить на завтра.';
  }

  /* ── Чипы: скользящая плашка активной вкладки ──────────────────────────── */

  function paintChips(cuisines) {
    chips.innerHTML = '<span class="chips__pill" id="chips-pill" hidden></span>' +
      '<button class="chip" type="button" data-cuisine="" aria-pressed="true">Все</button>' +
      cuisines.map(function (name) {
        return '<button class="chip" type="button" data-cuisine="' + EP.escapeHtml(name) +
          '" aria-pressed="false">' + EP.escapeHtml(name) + '</button>';
      }).join('');
    movePill(chips.querySelector('.chip[aria-pressed="true"]'));
  }

  function movePill(chip) {
    var pill = document.getElementById('chips-pill');
    if (!pill || !chip) return;
    pill.hidden = false;
    pill.style.width = chip.offsetWidth + 'px';
    pill.style.height = chip.offsetHeight + 'px';
    pill.style.transform = 'translate(' + chip.offsetLeft + 'px,' + chip.offsetTop + 'px)';
  }

  chips.addEventListener('click', function (event) {
    var chip = event.target.closest('button.chip');
    if (!chip) return;
    cuisine = chip.dataset.cuisine;
    chips.querySelectorAll('.chip').forEach(function (node) {
      node.setAttribute('aria-pressed', node === chip ? 'true' : 'false');
    });
    movePill(chip);
    paint();
  });

  searchInput.addEventListener('input', paint);
  searchInput.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { searchInput.value = ''; paint(); }
  });
  if (clearButton) {
    clearButton.addEventListener('click', function () {
      searchInput.value = '';
      searchInput.focus();
      paint();
    });
  }
  window.addEventListener('resize', function () {
    movePill(chips.querySelector('.chip[aria-pressed="true"]'));
  });

  /* ── Живые часы и параллакс баннера ────────────────────────────────────── */

  function paintClock() {
    if (!clock) return;
    var now = new Date();
    clock.textContent = String(now.getHours()).padStart(2, '0') + ':' +
      String(now.getMinutes()).padStart(2, '0');
  }

  var ticking = false;
  window.addEventListener('scroll', function () {
    if (ticking) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      var shift = Math.min(window.scrollY * 0.18, 3);
      /* Сдвигаем фото видимого слайда: у остальных своя анимация появления. */
      var active = document.querySelector('.promo__slide.is-on .promo__photo');
      if (active) active.style.transform = 'translateY(' + shift.toFixed(2) + 'px)';
      ticking = false;
    });
  }, { passive: true });

  /* ── Загрузка ──────────────────────────────────────────────────────────── */

  async function load() {
    try {
      var payload = await EP.apiFetch('/api/establishments/home');
      all = payload.places || [];
      popular = payload.popular || [];
      paintChips(payload.cuisines || []);
      paintPopular();
      paintSlides(buildSlides(payload.stats, all, popular));
      /* Отсчёт до ближайшей свободной минуты — тикает каждую секунду. */
      var soonest = all.filter(function (item) { return item.nearest_slot; })[0];
      if (soonest) {
        windowTarget = new Date(soonest.nearest_slot).getTime();
        paintWindowCard(soonest);
        tickWindow();
        window.setInterval(tickWindow, 1000);
      } else {
        windowCard.hidden = true;
      }
      host.setAttribute('aria-busy', 'false');
      paint();
      /* Блоки, появившиеся позже (карточка окна выдачи), тоже нужно наблюдать. */
      bindReveal();
    } catch (error) {
      host.innerHTML = '<div class="empty" style="grid-column:1/-1">' +
        '<h3>Не удалось загрузить список</h3><p>' + EP.escapeHtml(error.message) + '</p>' +
        '<button class="btn btn--flame" type="button" id="places-retry" style="margin-top:12px">' +
        'Повторить</button></div>';
      var retry = document.getElementById('places-retry');
      if (retry) retry.addEventListener('click', load);
    }
  }

  paintClock();
  window.setInterval(paintClock, 30000);
  load();
})();
