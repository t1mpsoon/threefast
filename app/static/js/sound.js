/* Мягкие звуки интерфейса: короткие «щелчки» на нажатиях.

   Звуки синтезируются через WebAudio, а не лежат файлами: нечего грузить,
   нет лишних запросов и легко сделать их тихими и разными по смыслу.
   По умолчанию звук включён, но его можно выключить — выбор запоминается. */
(function () {
  'use strict';

  var KEY = 'ep-sound';
  var context = null;
  var enabled = null;

  function isOn() {
    if (enabled !== null) return enabled;
    try {
      var saved = localStorage.getItem(KEY);
      enabled = saved === null ? true : saved === 'on';
    } catch (_) {
      enabled = true;
    }
    return enabled;
  }

  function audio() {
    if (!isOn()) return null;
    if (context) return context;
    var Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    try {
      context = new Ctor();
    } catch (_) {
      context = null;
    }
    return context;
  }

  /* Мягкий тон: короткая атака, длинный хвост — слышно как «тук», а не «бип». */
  function tone(frequency, options) {
    var ctx = audio();
    if (!ctx) return;
    var opts = options || {};
    if (ctx.state === 'suspended') ctx.resume();

    var duration = opts.duration || 0.09;
    var volume = opts.volume || 0.05;
    var now = ctx.currentTime;

    var oscillator = ctx.createOscillator();
    var gain = ctx.createGain();
    oscillator.type = opts.wave || 'sine';
    oscillator.frequency.setValueAtTime(frequency, now);
    if (opts.glide) {
      oscillator.frequency.exponentialRampToValueAtTime(opts.glide, now + duration);
    }

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(volume, now + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start(now);
    oscillator.stop(now + duration + 0.02);
  }

  var SOUNDS = {
    /* Добавили блюдо: короткий тон вверх. */
    add: function () { tone(660, { glide: 990, duration: 0.1, volume: 0.055 }); },
    /* Убрали: тон вниз, чуть мягче. */
    remove: function () { tone(440, { glide: 300, duration: 0.09, volume: 0.04 }); },
    /* Обычное нажатие: едва слышный щелчок. */
    tap: function () { tone(520, { duration: 0.05, volume: 0.028, wave: 'triangle' }); },
    /* Выбор времени: два тона подряд. */
    pick: function () {
      tone(620, { duration: 0.07, volume: 0.045 });
      window.setTimeout(function () { tone(880, { duration: 0.09, volume: 0.04 }); }, 70);
    },
    /* Заказ оформлен: короткая восходящая фраза. */
    success: function () {
      [523, 659, 784].forEach(function (note, index) {
        window.setTimeout(function () {
          tone(note, { duration: 0.16, volume: 0.05 });
        }, index * 110);
      });
    },
    /* Ошибка: один низкий тон без резкости. */
    error: function () { tone(220, { glide: 165, duration: 0.18, volume: 0.04, wave: 'triangle' }); },
    /* Смена статуса заказа на кухне. */
    status: function () { tone(740, { glide: 980, duration: 0.12, volume: 0.045 }); },
    /* Новый заказ на кухне: две ноты вверх, слышно из-за плиты.
       Смена не смотрит на экран, а заказ нужно начать вовремя. */
    new: function () {
      [660, 880].forEach(function (note, index) {
        window.setTimeout(function () {
          tone(note, { duration: 0.18, volume: 0.06 });
        }, index * 130);
      });
    }
  };

  function play(name) {
    if (!isOn()) return;
    var sound = SOUNDS[name];
    if (sound) sound();
  }

  function toggle() {
    enabled = !isOn();
    try { localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch (_) { /* приватный режим */ }
    if (enabled) play('tap');
    paint();
    return enabled;
  }

  function paint() {
    document.querySelectorAll('.sound-toggle').forEach(function (button) {
      button.setAttribute('aria-pressed', isOn() ? 'true' : 'false');
      button.setAttribute('title', isOn() ? 'Звук включён' : 'Звук выключен');
      button.setAttribute('aria-label',
        isOn() ? 'Звуки интерфейса включены. Выключить.' : 'Звуки интерфейса выключены. Включить.');
    });
  }

  /* Нажатия: слушаем весь документ, чтобы не вешать обработчик на каждую кнопку. */
  document.addEventListener('click', function (event) {
    var target = event.target.closest(
      '.btn, .chip, .tabbar__tab, .tabbar__theme, .shift, .quick__item, .slot, .segment label, ' +
      '.link-btn, .crew__tab, .promo__dot, .search__clear, .sound-toggle'
    );
    if (!target || target.closest('.sound-toggle')) return;
    if (target.matches('.chip, .slot, .segment label, .promo__dot')) {
      play('pick');
      return;
    }
    if (target.matches('.add-btn')) {
      play('add');
      return;
    }
    play('tap');
  });

  /* Добавление и удаление блюда: различаем по действию кнопки. */
  document.addEventListener('click', function (event) {
    var button = event.target.closest('.dish__side button, .add-btn, .stepper button');
    if (!button) return;
    play(button.dataset.act === 'less' ? 'remove' : 'add');
  }, true);

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.sound-toggle').forEach(function (button) {
      button.addEventListener('click', function () { toggle(); });
    });
    paint();
  });
  window.addEventListener('load', paint);

  window.EPSound = { play: play, toggle: toggle, isOn: isOn };
})();
