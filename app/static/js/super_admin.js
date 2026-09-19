/* Панель супер-администратора: заведения, доступы, пароли. */
(function () {
  'use strict';

  var host = document.getElementById('places-admin');
  var form = document.getElementById('place-form');
  var creds = document.getElementById('creds');
  if (!host || !form) return;

  var places = [];

  /* ── Список заведений ──────────────────────────────────────────────────── */

  function card(place) {
    var photo = place.photo
      ? '<img class="ops-card__photo" src="' + EP.escapeHtml(place.photo) + '" alt="" ' +
        'loading="lazy" width="320" height="200">'
      : '<span class="ops-card__photo ops-card__photo--empty"></span>';
    return '<article class="ops-card" data-place="' + place.id + '">' +
      '<span class="ops-card__media">' + photo +
        '<span class="ops-card__dishes">' + place.dishes_count + ' ' +
          EP.plural(place.dishes_count, 'блюдо', 'блюда', 'блюд') + '</span>' +
      '</span>' +
      '<div class="ops-card__body">' +
        '<div class="ops-card__name">' + EP.escapeHtml(place.name) + '</div>' +
        '<div class="ops-card__meta">' +
          EP.escapeHtml(place.cuisine || 'Кухня не указана') +
          (place.address ? ' · ' + EP.escapeHtml(place.address) : '') + '</div>' +
        '<div class="ops-card__meta">' +
          place.opens_at + '–' + place.closes_at + ' · ' +
          place.slot_capacity + ' ' + EP.plural(place.slot_capacity, 'порция', 'порции', 'порций') +
        ' каждые ' + place.slot_duration_minutes + ' мин</div>' +
        /* Доступы строками: подпись слева, логин справа. Раньше это были
           метки в одну строку, и длинное название кафе ломало их на две
           строки — читалось хуже, чем таблица. */
        '<dl class="ops-card__logins">' +
          '<div class="ops-login">' +
            '<dt>Администратор кафе</dt>' +
            '<dd>' + EP.escapeHtml(place.admin_login || '—') + '</dd>' +
          '</div>' +
          '<div class="ops-login">' +
            '<dt>Смена кухни</dt>' +
            '<dd>' + EP.escapeHtml(place.staff_login || '—') + '</dd>' +
          '</div>' +
        '</dl>' +
      '</div>' +
      '<div class="ops-card__acts">' +
        '<button class="link-btn" data-act="edit">Изменить</button>' +
        '<button class="link-btn" data-act="password">Новый пароль</button>' +
        '<a class="link-btn" href="/e/' + place.id + '/menu" target="_blank" rel="noopener">' +
          'Открыть меню</a>' +
      '</div>' +
    '</article>';
  }

  function paint() {
    document.getElementById('ops-count').textContent =
      places.length + ' ' + EP.plural(places.length, 'заведение', 'заведения', 'заведений');
    host.innerHTML = places.map(card).join('');
    EP.stagger(host.querySelectorAll('.ops-card'), { step: 60, base: 40 });

    var list = document.getElementById('cuisine-list');
    if (list) {
      var names = [];
      places.forEach(function (place) {
        if (place.cuisine && names.indexOf(place.cuisine) === -1) names.push(place.cuisine);
      });
      list.innerHTML = names.map(function (name) {
        return '<option value="' + EP.escapeHtml(name) + '"></option>';
      }).join('');
    }
  }

  /* ── Сводка по платформе ───────────────────────────────────────────────── */

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  async function loadPlatform() {
    var box = document.getElementById('platform-stats');
    if (!box) return;
    try {
      var report = await EP.apiFetch('/api/super/analytics?period=day');
      setText('plat-orders', report.orders_count);
      setText('plat-orders-note',
        'выдано ' + report.picked_up_count + ' · не забрали ' + report.lost_orders_count);

      var wait = report.average_wait_minutes;
      var waitNode = document.getElementById('plat-wait');
      setText('plat-wait', wait === null ? '—' : wait + ' мин');
      if (waitNode) {
        waitNode.classList.toggle('plat__value--good', Boolean(report.wait_target_met));
        waitNode.classList.toggle('plat__value--warn',
          wait !== null && !report.wait_target_met);
      }
      setText('plat-wait-note', wait === null
        ? 'пока нет выданных заказов'
        : (report.wait_target_met ? 'цель 2 минуты выполнена' : 'цель 2 минуты не достигнута'));

      setText('plat-active', report.active_places + ' из ' + report.places_total);
      setText('plat-active-note', report.idle_places
        ? 'простаивают: ' + report.idle_places
        : 'все точки приняли заказы');

      setText('plat-revenue', EP.money(report.revenue));
      setText('plat-revenue-note', report.period === 'day' ? 'за сегодня' : 'за период');
    } catch (_) {
      /* Сводка не критична: список заведений важнее. */
    }
  }

  async function load() {
    try {
      places = await EP.apiFetch('/api/super/places');
      paint();
    } catch (error) {
      host.innerHTML = '<div class="empty"><h3>Не удалось загрузить список</h3><p>' +
        EP.escapeHtml(error.message) + '</p></div>';
    }
  }

  /* ── Доступы: показываем один раз ──────────────────────────────────────── */

  function showCreds(payload) {
    creds.hidden = false;
    creds.innerHTML =
      '<div class="creds__head">' +
        '<strong>Доступ для «' + EP.escapeHtml(payload.place.name) + '»</strong>' +
        '<button class="link-btn link-btn--muted" type="button" id="creds-close">Скрыть</button>' +
      '</div>' +
      '<p class="creds__note">' + EP.escapeHtml(payload.message) + '</p>' +
      '<div class="creds__rows">' +
        row('Администратор точки', payload.admin_login, payload.password) +
        row('Смена кухни', payload.staff_login, payload.password) +
      '</div>' +
      '<button class="btn btn--line btn--sm" type="button" id="creds-copy">Скопировать доступы</button>';
    EP.nudge(creds, 'enter');
    creds.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    document.getElementById('creds-close').addEventListener('click', function () {
      creds.hidden = true;
    });
    document.getElementById('creds-copy').addEventListener('click', async function () {
      var text = 'Панель: ' + window.location.origin + '/login\n' +
        'Администратор: ' + payload.admin_login + ' / ' + payload.password + '\n' +
        'Кухня: ' + payload.staff_login + ' / ' + payload.password;
      try {
        await navigator.clipboard.writeText(text);
        EP.say('Доступы скопированы — передайте их заведению.', 'good');
      } catch (_) {
        EP.say('Скопируйте доступы вручную: ' + text, 'info', { sticky: true });
      }
    });
  }

  function row(title, login, password) {
    return '<div class="creds__row">' +
      '<span class="creds__label">' + EP.escapeHtml(title) + '</span>' +
      '<code class="creds__login">' + EP.escapeHtml(login || '—') + '</code>' +
      '<code class="creds__password">' + EP.escapeHtml(password) + '</code>' +
    '</div>';
  }

  /* ── Форма ─────────────────────────────────────────────────────────────── */

  var passwordField = document.getElementById('place-password-field');

  function openForm(place) {
    form.hidden = false;
    document.getElementById('place-form-title').textContent =
      place ? 'Правка: ' + place.name : 'Новое заведение';
    document.getElementById('place-id').value = place ? place.id : '';
    document.getElementById('place-name').value = place ? place.name : '';
    document.getElementById('place-address').value = place ? place.address : '';
    document.getElementById('place-cuisine').value = place ? place.cuisine : '';
    document.getElementById('place-photo').value = place ? place.photo : '';
    document.getElementById('place-open').value = place ? place.opens_at : '09:00';
    document.getElementById('place-close').value = place ? place.closes_at : '21:00';
    document.getElementById('place-step').value = place ? place.slot_duration_minutes : 5;
    document.getElementById('place-capacity').value = place ? place.slot_capacity : 3;
    document.getElementById('place-rating').value = place ? place.rating : 4.8;
    document.getElementById('place-baseline-orders').value = place ? 35 : 35;
    document.getElementById('place-baseline-wait').value = place ? 20 : 20;
    document.getElementById('place-password').value = '';
    /* Пароль задаётся только при создании: у существующей точки есть кнопка смены. */
    passwordField.hidden = Boolean(place);
    document.getElementById('place-save').textContent =
      place ? 'Сохранить изменения' : 'Создать заведение';
    paintCapacity();
    form.classList.remove('enter');
    void form.offsetWidth;
    form.classList.add('enter');
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    document.getElementById('place-name').focus();
  }

  function paintCapacity() {
    var step = Number(document.getElementById('place-step').value) || 5;
    var capacity = Number(document.getElementById('place-capacity').value) || 3;
    var perHour = Math.round(60 / step * capacity);
    document.getElementById('place-capacity-note').textContent =
      'Кухня успевает ' + perHour + ' ' +
        EP.plural(perHour, 'порция', 'порции', 'порций') + ' в час.';
  }

  document.getElementById('place-step').addEventListener('input', paintCapacity);
  document.getElementById('place-capacity').addEventListener('input', paintCapacity);
  document.getElementById('place-new').addEventListener('click', function () { openForm(null); });
  document.getElementById('place-cancel').addEventListener('click', function () {
    form.hidden = true;
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    EP.clearNotices();
    EP.cleanFields(form);

    var id = document.getElementById('place-id').value;
    var name = document.getElementById('place-name').value.trim();
    if (name.length < 2) {
      EP.badField('place-name', 'Название нужно, иначе гости его не увидят');
      return;
    }

    var body = {
      name: name,
      address: document.getElementById('place-address').value.trim(),
      cuisine: document.getElementById('place-cuisine').value.trim(),
      photo: document.getElementById('place-photo').value.trim(),
      rating: Number(document.getElementById('place-rating').value),
      opens_at: document.getElementById('place-open').value,
      closes_at: document.getElementById('place-close').value,
      slot_duration_minutes: Number(document.getElementById('place-step').value),
      slot_capacity: Number(document.getElementById('place-capacity').value),
      baseline_orders_per_day: Number(document.getElementById('place-baseline-orders').value),
      baseline_wait_minutes: Number(document.getElementById('place-baseline-wait').value)
    };
    if (!id) {
      var password = document.getElementById('place-password').value.trim();
      if (password) body.admin_password = password;
    }

    var button = document.getElementById('place-save');
    EP.busy(button, 'Сохраняем', async function () {
      try {
        if (id) {
          await EP.apiFetch('/api/super/places/' + id, {
            method: 'PUT', body: JSON.stringify(body)
          });
          EP.say('Заведение обновлено.', 'good');
          form.hidden = true;
        } else {
          var created = await EP.apiFetch('/api/super/places', {
            method: 'POST', body: JSON.stringify(body)
          });
          showCreds(created);
          form.hidden = true;
        }
        await load();
      } catch (error) {
        EP.say(error.message, 'bad', { title: 'Не сохранилось' });
      }
    });
  });

  host.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-act]');
    if (!button) return;
    var card = button.closest('.ops-card');
    var id = Number(card.dataset.place);
    var place = places.filter(function (one) { return one.id === id; })[0];
    if (!place) return;

    if (button.dataset.act === 'edit') {
      openForm(place);
      return;
    }

    var question = 'Выдать новый пароль для «' + place.name + '»? ' +
      'Прежний перестанет работать сразу.';
    if (!window.confirm(question)) return;

    EP.busy(button, 'Меняем', async function () {
      try {
        var payload = await EP.apiFetch('/api/super/places/' + id + '/password',
          { method: 'POST' });
        showCreds(payload);
        await load();
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  document.querySelectorAll('#crew-out, #crew-out-2').forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      EP.apiFetch('/api/auth/logout', { method: 'POST' })
        .catch(function () { /* сессия и так истечёт */ })
        .then(function () { EP.go('/login'); });
    });
  });

  load();
  loadPlatform();
})();
