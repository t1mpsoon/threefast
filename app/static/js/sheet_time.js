/* Шторка выбора времени: барабаны часов и минут, как будильник в телефоне.

   Логика подчинена одному правилу: назад во времени уйти нельзя. Барабаны
   строятся только из доступных слотов, поэтому прошедших значений в них
   просто нет — исключать их отдельно не приходится. */
(function () {
  'use strict';

  var placeId = window.PLACE_ID;
  var host = document.getElementById('time-host');
  var sumOut = document.getElementById('time-sum');
  var noteOut = document.getElementById('time-note');
  var confirmBtn = document.getElementById('time-confirm');
  var dayInput = document.getElementById('time-day');
  var dayBar = document.getElementById('day-bar');
  var dayPick = document.getElementById('day-pick');
  var dayPickLabel = document.getElementById('day-pick-label');
  var drumWrap = document.getElementById('time-drum');
  var loading = document.getElementById('time-loading');
  var hourDrum = document.getElementById('hour-drum');
  var minuteDrum = document.getElementById('minute-drum');
  var nearestBtn = document.getElementById('time-nearest');
  if (!host || !hourDrum || !minuteDrum) return;

  var sheet = window.EP_SHEETS[0];
  var day = window.TODAY;
  var slots = [];
  var byHour = {};        /* час -> список доступных минут */
  var hours = [];         /* доступные часы по порядку */
  var hour = null;        /* выбранный час */
  var minute = null;      /* выбранная минута */
  var picked = Cart.minute().at || null;

  /* ── Даты ──────────────────────────────────────────────────────────────── */

  function iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function dateOfDay(offset) {
    var d = new Date(window.TODAY + 'T00:00:00');
    d.setDate(d.getDate() + offset);
    return iso(d);
  }

  function lastDay() {
    return dateOfDay(window.MAX_DAYS);
  }

  function humanDay(value) {
    if (value === window.TODAY) return 'Сегодня';
    if (value === dateOfDay(1)) return 'Завтра';
    var parts = value.split('-');
    return parts[2] + '.' + parts[1] + '.' + parts[0];
  }

  function paintDays() {
    dayBar.querySelectorAll('.daybar__day[data-day-offset]').forEach(function (button) {
      var value = dateOfDay(Number(button.dataset.dayOffset));
      button.classList.toggle('is-on', value === day);
      button.disabled = value > lastDay();
      button.setAttribute('aria-pressed', value === day ? 'true' : 'false');
    });
    var isToday = day === window.TODAY;
    var isTomorrow = day === dateOfDay(1);
    dayPick.classList.toggle('is-on', !isToday && !isTomorrow);
    dayPickLabel.textContent = isToday || isTomorrow ? 'Выбрать дату' : humanDay(day);
    dayInput.value = day;
    dayInput.max = lastDay();
  }

  /* ── Барабаны ──────────────────────────────────────────────────────────── */

  var ITEM = 48;   /* высота строки барабана, совпадает с CSS */

  function buildDrum(drum, values, selected, format) {
    /* Значения лежат прямо в окне барабана: прокручивается оно само, а
       отступы сверху и снизу заданы в CSS — они и ставят крайние значения
       по центру рамки. Так прилипание всегда попадает в целое значение. */
    drum.innerHTML = values.map(function (value) {
      return '<button class="slot' + (value === selected ? ' is-on' : '') +
        '" type="button" role="option" data-value="' + value + '"' +
        ' aria-selected="' + (value === selected ? 'true' : 'false') + '">' +
        format(value) + '</button>';
    }).join('');
    drum.dataset.values = values.join(',');
    scrollToValue(drum, selected, false);
  }

  function valueOf(drum) {
    var index = Math.round(drum.scrollTop / ITEM);
    var values = (drum.dataset.values || '').split(',').filter(Boolean);
    return values[Math.max(0, Math.min(index, values.length - 1))];
  }

  function scrollToValue(drum, value, smooth) {
    var values = (drum.dataset.values || '').split(',');
    var index = values.indexOf(String(value));
    if (index === -1) return;
    drum.scrollTo({ top: index * ITEM, behavior: smooth ? 'smooth' : 'auto' });
  }

  /* Прокрутка с прилипанием: подсвечиваем центральное значение и сообщаем
     наружу, что выбор изменился. */
  function bindDrum(drum, onPick) {
    if (drum.dataset.bound === '1') return;
    drum.dataset.bound = '1';
    var timer = null;
    /* Пока идёт программная прокрутка, обработчик scroll не должен
       «возвращать» прежнее значение: именно на этом ломался выбор нажатием. */
    var settleUntil = 0;

    drum.addEventListener('scroll', function () {
      highlight(drum);
      if (Date.now() < settleUntil) return;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        if (Date.now() < settleUntil) return;
        var value = valueOf(drum);
        settleUntil = Date.now() + 420;
        scrollToValue(drum, value, true);
        onPick(value);
      }, 130);
    }, { passive: true });

    /* Нажатие по значению выбирает его сразу: гость не обязан попадать
       прокруткой, а именно так и пытается — пальцем по цифре. */
    drum.addEventListener('click', function (event) {
      var item = event.target.closest('.slot');
      if (!item || !drum.contains(item)) return;
      var value = item.dataset.value;
      if (!value) return;
      settleUntil = Date.now() + 420;
      if (timer) window.clearTimeout(timer);
      scrollToValue(drum, value, true);
      highlight(drum, value);
      onPick(value);
    });

    drum.addEventListener('keydown', function (event) {
      var step = event.key === 'ArrowDown' ? 1 : (event.key === 'ArrowUp' ? -1 : 0);
      if (!step) return;
      event.preventDefault();
      var values = (drum.dataset.values || '').split(',');
      var index = values.indexOf(String(valueOf(drum))) + step;
      index = Math.max(0, Math.min(index, values.length - 1));
      settleUntil = Date.now() + 420;
      scrollToValue(drum, values[index], true);
      highlight(drum, values[index]);
      onPick(values[index]);
    });
  }

  function highlight(drum, forceValue) {
    var values = (drum.dataset.values || '').split(',');
    var index = forceValue === undefined
      ? Math.max(0, Math.min(Math.round(drum.scrollTop / ITEM), values.length - 1))
      : Math.max(0, values.indexOf(String(forceValue)));
    var items = drum.querySelectorAll('.slot');
    items.forEach(function (item, position) {
      item.classList.toggle('is-on', position === index);
      item.setAttribute('aria-selected', position === index ? 'true' : 'false');
    });
  }

  /* ── Данные и отрисовка ────────────────────────────────────────────────── */

  function minutesList(hourValue) {
    return byHour[hourValue] || [];
  }

  function pickTime(hourValue, minuteValue) {
    hour = hourValue;
    minute = minuteValue;
    var available = minutesList(hour);
    if (available.indexOf(minute) === -1) {
      minute = available[0] || null;
      if (minute !== null) scrollToValue(minuteDrum, minute, true);
      highlight(minuteDrum);
    }
    picked = minute === null ? null : day + 'T' + hour + ':' + minute + ':00';
    paintConfirm();
  }

  function onHourPicked(value) {
    if (value === hour) return;
    hour = value;
    var available = minutesList(hour);
    minute = available[0] || null;
    buildDrum(minuteDrum, available, minute, function (m) { return m; });
    bindDrum(minuteDrum, onMinutePicked);
    picked = minute === null ? null : day + 'T' + hour + ':' + minute + ':00';
    paintConfirm();
  }

  function onMinutePicked(value) {
    if (value === minute) return;
    minute = value;
    picked = day + 'T' + hour + ':' + minute + ':00';
    paintConfirm();
  }

  function discountOf(iso) {
    var found = 0;
    slots.forEach(function (s) { if (s.slot_datetime.slice(0, 16) === String(iso).slice(0, 16)) found = s.discount_percent || 0; });
    return found;
  }

  function paintConfirm() {
    var ready = Boolean(picked) && minute !== null;
    confirmBtn.disabled = !ready;
    confirmBtn.textContent = ready
      ? 'Подтвердить · ' + humanDay(day).toLowerCase() + ', ' + hour + ':' + minute +
        (discountOf(picked) ? ' · −' + discountOf(picked) + '%' : '')
      : 'Подтвердить время';
  }

  function showEmpty(why) {
    drumWrap.hidden = true;
    loading.hidden = true;
    host.innerHTML = '<div class="empty"><h3>' + EP.escapeHtml(why) + '</h3>' +
      '<p>Посмотрите следующий день — там время появится.</p>' +
      '<button class="btn btn--flame" type="button" id="time-tomorrow" style="margin-top:14px">' +
      'Показать завтра</button></div>';
    var tomorrow = document.getElementById('time-tomorrow');
    if (tomorrow) tomorrow.addEventListener('click', function () { goToDay(dateOfDay(1)); });
    sumOut.textContent = '';
    noteOut.hidden = true;
    picked = null;
    paintConfirm();
  }

  function paint() {
    var available = slots.filter(function (slot) { return slot.available; });
    host.innerHTML = '';

    if (!available.length) {
      var why = !slots.length
        ? 'В этот день заведение не работает.'
        : 'На этот день свободного времени не осталось.';
      showEmpty(why);
      return;
    }

    byHour = {};
    hours = [];
    available.forEach(function (slot) {
      var h = slot.slot_datetime.slice(11, 13);
      var m = slot.slot_datetime.slice(14, 16);
      if (!byHour[h]) { byHour[h] = []; hours.push(h); }
      byHour[h].push(m);
    });

    drumWrap.hidden = false;
    loading.hidden = true;
    sumOut.textContent = available.length + ' ' +
      EP.plural(available.length, 'минута', 'минуты', 'минут') + ' свободно' +
      (available.some(function (s) { return s.discount_percent; }) ? ' · вне часов пик дешевле' : '');

    /* Стартуем с ближайшего доступного времени: это то, что чаще всего нужно. */
    var first = available[0];
    var startHour = first.slot_datetime.slice(11, 13);
    var startMinute = first.slot_datetime.slice(14, 16);

    if (picked && picked.slice(0, 10) === day) {
      var pickedHour = picked.slice(11, 13);
      if (minutesList(pickedHour).length) {
        startHour = pickedHour;
        startMinute = minutesList(pickedHour).indexOf(picked.slice(14, 16)) !== -1
          ? picked.slice(14, 16) : minutesList(pickedHour)[0];
      }
    }

    hour = startHour;
    minute = startMinute;
    picked = day + 'T' + hour + ':' + minute + ':00';

    buildDrum(hourDrum, hours, hour, function (h) { return h; });
    buildDrum(minuteDrum, minutesList(hour), minute, function (m) { return m; });
    bindDrum(hourDrum, onHourPicked);
    bindDrum(minuteDrum, onMinutePicked);

    /* Подсказка о причине, если часть времени скрыта. */
    var hidden = slots.length - available.length;
    if (hidden > 0 && day === window.TODAY) {
      noteOut.hidden = false;
      noteOut.textContent = 'Ближайшие ' + hidden + ' ' +
        EP.plural(hidden, 'минута', 'минуты', 'минут') +
        ' недоступны: кухня успеет приготовить только позже.';
    } else {
      noteOut.hidden = true;
    }

    paintConfirm();
  }

  async function load() {
    drumWrap.hidden = true;
    loading.hidden = false;
    host.innerHTML = '';
    noteOut.hidden = true;
    try {
      var payload = await EP.apiFetch(
        '/api/establishments/' + placeId + '/slots?date=' + encodeURIComponent(day) +
        '&min_prep_minutes=' + Cart.cooksFor()
      );
      slots = payload.slots || [];
      paint();
    } catch (error) {
      loading.hidden = true;
      host.innerHTML = '<div class="empty"><h3>Время не загрузилось</h3><p>' +
        EP.escapeHtml(error.message) + '</p></div>';
    }
  }

  function goToDay(value) {
    if (value < window.TODAY || value > lastDay()) return;
    day = value;
    paintDays();
    load();
  }

  /* ── События ───────────────────────────────────────────────────────────── */

  dayBar.addEventListener('click', function (event) {
    var button = event.target.closest('.daybar__day[data-day-offset]');
    if (!button || button.disabled) return;
    goToDay(dateOfDay(Number(button.dataset.dayOffset)));
  });

  dayPick.addEventListener('click', function () {
    if (typeof dayInput.showPicker === 'function') {
      dayInput.showPicker();
    } else {
      dayInput.click();
    }
  });

  dayInput.addEventListener('change', function () {
    if (dayInput.value && dayInput.value >= window.TODAY) goToDay(dayInput.value);
  });

  nearestBtn.addEventListener('click', function () {
    if (!hours.length) return;
    var firstHour = hours[0];
    hour = firstHour;
    minute = minutesList(firstHour)[0];
    picked = day + 'T' + hour + ':' + minute + ':00';
    scrollToValue(hourDrum, hour, true);
    buildDrum(minuteDrum, minutesList(hour), minute, function (m) { return m; });
    bindDrum(minuteDrum, onMinutePicked);
    highlight(hourDrum);
    highlight(minuteDrum);
    paintConfirm();
  });

  confirmBtn.addEventListener('click', function () {
    if (!picked || minute === null) return;
    Cart.setMinute(picked, humanDay(day) + ', ' + hour + ':' + minute, discountOf(picked));
    sheet.close();
    /* Шторка времени закрывается — сразу открываем оформление. */
    window.setTimeout(function () {
      if (window.CheckoutSheet) window.CheckoutSheet.open();
    }, 320);
  });

  window.addEventListener('resize', function () {
    if (drumWrap.hidden) return;
    if (hour) scrollToValue(hourDrum, hour, false);
    if (minute) scrollToValue(minuteDrum, minute, false);
    highlight(hourDrum);
    highlight(minuteDrum);
  });

  window.TimeSheet = {
    open: function () {
      if (day < window.TODAY) day = window.TODAY;
      picked = Cart.minute().at || null;
      paintDays();
      paintConfirm();
      sheet.open();
      load();
    }
  };
})();
