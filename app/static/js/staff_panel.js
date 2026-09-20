/* Панель кухни: очередь заказов, правка меню и настройки на одном экране.
   Никаких переходов между страницами — вкладки переключаются на месте. */
(function () {
  'use strict';

  var root = document.getElementById('crew');
  if (!root) return;

  var host = document.getElementById('orders');
  var refresh = document.getElementById('crew-refresh');

  /* Роль вошедшего. От неё зависит, что показываем: правка меню и настройки
     на бэкенде защищены require_admin, поэтому кухне их не рисуем вовсе,
     а не прячем в неактивном виде. */
  var isAdmin = root.dataset.role === 'admin';

  var orders = [];
  var settings = null;
  /* Отпечаток последней отрисовки очереди: по нему понимаем, изменилось ли
     что-то на самом деле. Без него каждые несколько секунд заново играла
     анимация появления, сбрасывались выделение и позиция прокрутки. */
  var lastPainted = null;

  var NEXT = {
    confirmed: { to: 'in_progress', label: 'Начать готовить' },
    in_progress: { to: 'ready', label: 'Отметить готовым' },
    ready: { to: 'picked_up', label: 'Отдал гостю' }
  };

  /* ── Очередь ───────────────────────────────────────────────────────────── */

  function dishes(order) {
    return (order.items || []).map(function (item) {
      return EP.escapeHtml(item.item_name_snapshot) + ' ×' + item.quantity;
    }).join(', ') || '—';
  }

  function rowHtml(order) {
    var acts = '';
    var next = NEXT[order.status];
    if (next && order.allowed_transitions.indexOf(next.to) !== -1) {
      acts += '<button class="btn btn--flame btn--sm" data-move="' + next.to +
        '" data-version="' + order.version + '" data-id="' + order.id + '">' +
        next.label + '</button>';
    }
    if (order.allowed_transitions.indexOf('cancelled') !== -1) {
      acts += '<button class="link-btn link-btn--muted" data-move="cancelled" ' +
        'data-confirm="1" data-version="' + order.version + '" data-id="' + order.id +
        '">Гость не придёт</button>';
    }

    return '<article class="ticket" data-id="' + order.id + '" data-at="' + order.slot_datetime +
      '" data-tone="' + (order.status_tone || 'guest') + '">' +
      '<div class="ticket__time">' +
        '<span class="ticket__at">' + EP.timeOf(order.slot_datetime) + '</span>' +
        '<span class="ticket__left" data-role="left">—</span>' +
      '</div>' +
      '<div class="ticket__body">' +
        '<div class="ticket__top">' +
          '<span class="ticket__code">' + EP.escapeHtml(order.order_code) + '</span>' +
          '<span class="badge badge--' + (order.status_tone || 'guest') + '">' +
            EP.escapeHtml(order.status_title) + '</span>' +
        '</div>' +
        '<div class="ticket__guest">' + EP.escapeHtml(order.guest_name) +
          ' <span class="muted">' + EP.escapeHtml(order.guest_phone) + '</span></div>' +
        /* Столик виден сразу: смена несёт заказ к гостю, а не выкликивает номер. */
        (order.table_number
          ? '<div class="ticket__table">Стол ' + Number(order.table_number) + '</div>'
          : '') +
        '<div class="ticket__dishes">' + dishes(order) + '</div>' +
        (order.note
          ? '<div class="ticket__note">' +
              '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
                '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="2"/>' +
                '<path d="M12 8.5v.01M11.2 12h.8v4h.8" stroke="currentColor" stroke-width="2" ' +
                'stroke-linecap="round" stroke-linejoin="round"/>' +
              '</svg>' +
              EP.escapeHtml(order.note) + '</div>'
          : '') +
      '</div>' +
      '<div class="ticket__side">' +
        '<span class="ticket__sum">' + EP.money(order.total_amount) + '</span>' +
        '<div class="ticket__acts">' + acts + '</div>' +
      '</div>' +
    '</article>';
  }

  function secondsLeft(node) {
    var at = new Date(node.dataset.at);
    if (isNaN(at.getTime())) return null;
    return Math.round((at - new Date()) / 1000);
  }

  function leftLabel(seconds, status) {
    if (seconds === null) return '—';
    if (status === 'ready') return 'на полке';
    if (seconds < 0) {
      var late = Math.abs(seconds);
      return late >= 60 ? 'опаздывает ' + Math.floor(late / 60) + ' мин' : 'опаздывает';
    }
    if (seconds < 60) return 'через ' + seconds + ' с';
    return 'через ' + Math.floor(seconds / 60) + ' мин';
  }

  function tick() {
    host.querySelectorAll('.ticket').forEach(function (node) {
      var left = secondsLeft(node);
      var status = node.dataset.status || '';
      var out = node.querySelector('[data-role="left"]');
      if (out) out.textContent = leftLabel(left, status);
      node.classList.toggle('ticket--late', left !== null && left <= 300 && left >= -60);
      node.classList.toggle('ticket--overdue', left !== null && left < 0);
    });
  }

  function queueSignature() {
    return orders.map(function (order) {
      return order.id + ':' + order.status + ':' + order.version;
    }).join(',');
  }

  function paint() {
    var fresh = queueSignature();
    if (fresh === lastPainted) return;
    lastPainted = fresh;
    if (!orders.length) {
      host.innerHTML = '<div class="empty">' +
        '<h3>Очередь пуста</h3>' +
        '<p>На этот день заказов нет. Новые появятся здесь сами — обновлять не нужно.</p>' +
        '</div>';
      return;
    }
    host.innerHTML = orders.map(rowHtml).join('');
    orders.forEach(function (order, index) {
      var node = host.querySelector('.ticket[data-id="' + order.id + '"]');
      if (node) {
        node.dataset.status = order.status;
        node.classList.add('enter');
        node.style.animationDelay = Math.min(index * 45, 400) + 'ms';
      }
    });
    tick();
  }

  /* Что уже видели: по этому понимаем, что пришёл новый заказ. */
  var knownOrders = null;

  async function loadOrders() {
    try {
      orders = await EP.apiFetch('/api/staff/orders');
      noticeNewOrders();
      paint();
    } catch (error) {
      /* Сессия истекла — возвращаем на вход, а не оставляем смену в тупике. */
      if (error.status === 401) {
        EP.go('/login');
        return;
      }
      /* Список затёрт сообщением об ошибке: следующий удачный ответ
         обязан перерисовать его, даже если данные не изменились. */
      lastPainted = null;
      host.innerHTML = '<div class="empty"><h3>Не удалось загрузить очередь</h3><p>' +
        EP.escapeHtml(error.message) + '</p></div>';
    }
  }

  /* Новый заказ нужно услышать: смена стоит у плиты и на экран не смотрит.
     Первую загрузку за новые заказы не считаем — иначе звук на каждый вход. */
  function noticeNewOrders() {
    var ids = orders.map(function (order) { return order.id; });
    if (knownOrders === null) {
      knownOrders = ids;
      return;
    }
    var fresh = ids.filter(function (id) { return knownOrders.indexOf(id) === -1; });
    knownOrders = ids;
    if (!fresh.length) return;
    if (window.EPSound) window.EPSound.play('new');
    var titles = orders
      .filter(function (order) { return fresh.indexOf(order.id) !== -1; })
      .map(function (order) { return order.order_code + ' на ' + EP.timeOf(order.slot_datetime); });
    EP.say(
      'Новый заказ: ' + titles.join(', ') + '.',
      'good',
      { title: fresh.length > 1 ? 'Новые заказы' : 'Новый заказ' }
    );
  }

  /* Смена статуса: главное действие кухни. Версия записи защищает от гонки. */
  host.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-move]');
    if (!button) return;

    /* Отмена заказа — единственное действие, которое нельзя отменить обратно.
       Поэтому спрашиваем подтверждение: первое нажатие меняет подпись, второе
       в течение пяти секунд отправляет. Промах пальцем больше не стоит заказа. */
    if (button.dataset.confirm === '1' && button.dataset.asked !== '1') {
      button.dataset.asked = '1';
      button.dataset.label = button.textContent;
      button.textContent = 'Точно отменить?';
      button.classList.add('link-btn--danger');
      window.setTimeout(function () {
        if (!button.isConnected || button.dataset.asked !== '1') return;
        button.dataset.asked = '';
        button.textContent = button.dataset.label || 'Гость не придёт';
        button.classList.remove('link-btn--danger');
      }, 5000);
      return;
    }

    var id = Number(button.dataset.id);
    var version = Number(button.dataset.version);
    EP.busy(button, 'Меняем', async function () {
      try {
        await EP.apiFetch('/api/staff/orders/' + id + '/status', {
          method: 'PATCH',
          body: JSON.stringify({ new_status: button.dataset.move, version: version })
        });
        if (window.EPSound) window.EPSound.play('status');
        await loadOrders();
      } catch (error) {
        if (error.status === 409) {
          EP.say('Заказ уже изменил кто-то другой — обновили очередь.', 'warn');
          await loadOrders();
          return;
        }
        EP.say(error.message, 'bad');
        if (window.EPSound) window.EPSound.play('error');
      }
    });
  });

  refresh.addEventListener('click', function () {
    loadOrders();
  });

  /* Короткий помощник: подставить текст по id, если элемент есть. */
  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  /* ── Вкладки ───────────────────────────────────────────────────────────── */

  var tabs = root.querySelectorAll('.crew__tab');
  var pill = document.getElementById('crew-pill');

  function movePill(tab) {
    if (!pill || !tab) return;
    pill.style.width = tab.offsetWidth + 'px';
    pill.style.transform = 'translateX(' + tab.offsetLeft + 'px)';
  }

  function showPanel(name) {
    root.querySelectorAll('.crew__panel').forEach(function (panel) {
      var on = panel.dataset.panel === name;
      panel.classList.toggle('is-on', on);
      panel.hidden = !on;
      if (on) {
        panel.classList.remove('enter');
        void panel.offsetWidth;
        panel.classList.add('enter');
      }
    });
    tabs.forEach(function (tab) {
      var on = tab.dataset.panel === name;
      tab.classList.toggle('is-on', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) movePill(tab);
    });
    if (name === 'menu') loadMenu();
    if (name === 'settings' && isAdmin) loadSettings();
    if (name === 'report' && isAdmin) loadReport('day');
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () { showPanel(tab.dataset.panel); });
  });

  /* ── Меню: список и правка на месте ────────────────────────────────────── */

  var menuHost = document.getElementById('menu-body');
  var form = document.getElementById('dish-form');
  var menuLoaded = false;
  var menuItems = [];

  async function loadMenu(force) {
    if (menuLoaded && !force) return;
    try {
      menuItems = await EP.apiFetch('/api/staff/menu');
      menuLoaded = true;
      paintMenu();
    } catch (error) {
      menuHost.innerHTML = '<div class="empty"><p>' + EP.escapeHtml(error.message) + '</p></div>';
    }
  }

  /* Меню заведения. Кухня видит состав и цены, но менять не может:
     ручки создания, правки и скрытия на бэкенде требуют администратора. */
  function menuSideHtml(item) {
    var price = '<span class="menu-card__price">' + EP.money(item.price) + '</span>';
    if (!isAdmin) {
      return '<div class="menu-card__side">' + price +
        '<span class="badge badge--glass">только просмотр</span>' +
      '</div>';
    }
    return '<div class="menu-card__side">' + price +
      '<div class="row" style="gap:6px">' +
        '<button class="link-btn" data-act="edit">Изменить</button>' +
        '<button class="link-btn" data-act="show">' +
          (item.is_active ? 'Скрыть' : 'Показать') + '</button>' +
      '</div>' +
    '</div>';
  }

  function paintMenu() {
    var categories = [];
    menuItems.forEach(function (item) {
      var name = item.category || 'Прочее';
      if (categories.indexOf(name) === -1) categories.push(name);
    });
    var list = document.getElementById('dish-cats');
    if (list) {
      list.innerHTML = categories.map(function (name) {
        return '<option value="' + EP.escapeHtml(name) + '"></option>';
      }).join('');
    }

    setText('menu-count', menuItems.length + ' ' +
      EP.plural(menuItems.length, 'позиция', 'позиции', 'позиций') +
      ' · скрытых: ' + menuItems.filter(function (i) { return !i.is_active; }).length);

    menuHost.innerHTML = menuItems.map(function (item) {
      return '<article class="menu-card' + (item.is_active ? '' : ' menu-card--off') +
        '" data-item="' + item.id + '">' +
        '<img class="menu-card__photo" src="' + EP.escapeHtml(item.photo || '') + '" alt="" ' +
          'loading="lazy" width="120" height="90">' +
        '<div class="menu-card__body">' +
          '<div class="menu-card__name">' + EP.escapeHtml(item.name) + '</div>' +
          '<div class="menu-card__meta">' + EP.escapeHtml(item.category || 'Прочее') +
            ' · ' + item.prep_time_minutes + ' мин' +
            (item.is_active ? '' : ' · скрыто от гостей') + '</div>' +
        '</div>' +
        menuSideHtml(item) +
      '</article>';
    }).join('');
    EP.stagger(menuHost.querySelectorAll('.menu-card'), { step: 35, base: 20 });
  }

  menuHost.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-act]');
    /* Кухне кнопок правки не рисуем — обработчик просто не найдёт цель. */
    if (!button || !isAdmin) return;
    var card = button.closest('.menu-card');
    var id = Number(card.dataset.item);
    var item = menuItems.filter(function (one) { return one.id === id; })[0];
    if (!item) return;

    if (button.dataset.act === 'edit') {
      openEditor(item);
      return;
    }
    EP.busy(button, 'Меняем', async function () {
      try {
        await EP.apiFetch('/api/staff/menu/' + id + '/active?is_active=' + (!item.is_active),
          { method: 'PATCH' });
        EP.say(item.is_active ? 'Блюдо скрыто из меню.' : 'Блюдо снова видно гостям.', 'good');
        await loadMenu(true);
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  function openEditor(item) {
    form.hidden = false;
    setText('dish-title', item ? 'Правка: ' + item.name : 'Новое блюдо');
    document.getElementById('dish-id').value = item ? item.id : '';
    document.getElementById('dish-name').value = item ? item.name : '';
    document.getElementById('dish-cat').value = item ? (item.category || '') : '';
    document.getElementById('dish-desc').value = item ? (item.description || '') : '';
    document.getElementById('dish-price').value = item ? Math.round(item.price) : '';
    document.getElementById('dish-cooks').value = item ? item.prep_time_minutes : 5;
    document.getElementById('dish-photo').value = item ? (item.photo || '') : '';
    document.getElementById('dish-on').checked = item ? Boolean(item.is_active) : true;
    paintPhotoPreview();
    form.classList.remove('enter');
    void form.offsetWidth;
    form.classList.add('enter');
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    document.getElementById('dish-name').focus();
  }

  function paintPhotoPreview() {
    var path = document.getElementById('dish-photo').value.trim();
    var preview = document.getElementById('dish-photo-preview');
    if (!preview) return;
    if (!path) {
      preview.hidden = true;
      preview.removeAttribute('src');
      return;
    }
    preview.src = path;
    preview.hidden = false;
    preview.onerror = function () { preview.hidden = true; };
    preview.onload = function () { preview.hidden = false; };
  }

  /* Редактор блюда целиком относится к администратору заведения: для кухни
     этих элементов в разметке нет, поэтому и обработчики не навешиваем. */
  var dishNew = document.getElementById('dish-new');
  var dishPhoto = document.getElementById('dish-photo');
  if (dishPhoto) dishPhoto.addEventListener('input', paintPhotoPreview);
  if (dishNew) dishNew.addEventListener('click', function () { openEditor(null); });
  var dishCancel = document.getElementById('dish-cancel');
  if (dishCancel) dishCancel.addEventListener('click', function () { form.hidden = true; });
  var dishReset = document.getElementById('dish-reset');
  if (dishReset) dishReset.addEventListener('click', function () { openEditor(null); });

  if (form) form.addEventListener('submit', function (event) {
    event.preventDefault();
    EP.clearNotices();
    EP.cleanFields(form);

    var id = document.getElementById('dish-id').value;
    var body = {
      name: document.getElementById('dish-name').value.trim(),
      category: document.getElementById('dish-cat').value.trim() || 'Прочее',
      description: document.getElementById('dish-desc').value.trim() || null,
      price: Number(document.getElementById('dish-price').value),
      prep_time_minutes: Number(document.getElementById('dish-cooks').value),
      photo: document.getElementById('dish-photo').value.trim() || null,
      is_active: document.getElementById('dish-on').checked
    };

    if (!body.name) { EP.badField('dish-name', 'Название не должно быть пустым'); return; }
    if (!(body.price >= 0)) { EP.badField('dish-price', 'Укажите цену числом'); return; }
    if (!(body.prep_time_minutes >= 1)) { EP.badField('dish-cooks', 'Хотя бы одна минута'); return; }

    var button = document.getElementById('dish-save');
    EP.busy(button, 'Сохраняем', async function () {
      try {
        await EP.apiFetch(id ? '/api/staff/menu/' + id : '/api/staff/menu', {
          method: id ? 'PUT' : 'POST',
          body: JSON.stringify(body)
        });
        EP.say(id ? 'Блюдо обновлено.' : 'Блюдо добавлено в меню.', 'good');
        form.hidden = true;
        await loadMenu(true);
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  /* ── Настройки ─────────────────────────────────────────────────────────── */

  var settingsForm = document.getElementById('settings-form');

  async function loadSettings(force) {
    if (!settingsForm || (settings && !force)) return;
    try {
      settings = await EP.apiFetch('/api/staff/settings');
      document.getElementById('set-open').value = settings.opens_at;
      document.getElementById('set-close').value = settings.closes_at;
      document.getElementById('set-step').value = settings.slot_duration_minutes;
      document.getElementById('set-capacity').value = settings.slot_capacity;
      document.getElementById('set-orders').value = settings.baseline_orders_per_day;
      document.getElementById('set-wait').value = Math.round(settings.baseline_wait_minutes);
      paintCapacityNote();
      loadProfile();
    } catch (error) {
      EP.say(error.message, 'bad');
    }
  }

  /* Профиль заведения: адрес, фото, кухня и часы. Размеры слотов и
     вместимость сюда не входят — они в основной форме настроек. */
  async function loadProfile() {
    var form = document.getElementById('profile-form');
    if (!form) return;
    try {
      var profile = await EP.apiFetch('/api/staff/profile');
      document.getElementById('profile-address').value = profile.address || '';
      document.getElementById('profile-photo').value = profile.photo || '';
      document.getElementById('profile-cuisine').value = profile.cuisine || '';
      document.getElementById('profile-open').value = profile.opens_at;
      document.getElementById('profile-close').value = profile.closes_at;
    } catch (error) {
      EP.say(error.message, 'bad');
    }
  }

  function paintCapacityNote() {
    if (!settings) return;
    var perHour = Math.round(60 / settings.slot_duration_minutes * settings.slot_capacity);
    var node = document.getElementById('capacity-note');
    if (node) {
      node.textContent = 'Кухня успевает ' + perHour + ' порций в час: ' +
        settings.slot_capacity + ' порций каждые ' + settings.slot_duration_minutes + ' мин.';
    }
  }

  var setStep = document.getElementById('set-step');
  var setCapacity = document.getElementById('set-capacity');
  if (setStep) setStep.addEventListener('input', paintCapacityNote);
  if (setCapacity) setCapacity.addEventListener('input', paintCapacityNote);

  if (settingsForm) settingsForm.addEventListener('submit', function (event) {
    event.preventDefault();
    var button = document.getElementById('set-save');
    var body = {
      opens_at: document.getElementById('set-open').value,
      closes_at: document.getElementById('set-close').value,
      slot_duration_minutes: Number(document.getElementById('set-step').value),
      slot_capacity: Number(document.getElementById('set-capacity').value),
      baseline_orders_per_day: Number(document.getElementById('set-orders').value),
      baseline_wait_minutes: Number(document.getElementById('set-wait').value)
    };
    EP.busy(button, 'Сохраняем', async function () {
      try {
        settings = await EP.apiFetch('/api/staff/settings', {
          method: 'PUT', body: JSON.stringify(body)
        });
        paintCapacityNote();
        EP.say('Настройки сохранены. Будущие слоты уже с новой вместимостью.', 'good');
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  /* Сохранение профиля заведения: адрес, фото, кухня, часы. */
  var profileForm = document.getElementById('profile-form');
  if (profileForm) profileForm.addEventListener('submit', function (event) {
    event.preventDefault();
    var button = document.getElementById('profile-save');
    var body = {
      address: document.getElementById('profile-address').value.trim(),
      cuisine: document.getElementById('profile-cuisine').value.trim(),
      photo: document.getElementById('profile-photo').value.trim(),
      opens_at: document.getElementById('profile-open').value,
      closes_at: document.getElementById('profile-close').value
    };
    if (!body.opens_at || !body.closes_at) {
      EP.say('Укажите часы работы: открытие и закрытие вместе.', 'bad');
      return;
    }
    EP.busy(button, 'Сохраняем', async function () {
      try {
        await EP.apiFetch('/api/staff/profile', {
          method: 'PUT', body: JSON.stringify(body)
        });
        EP.say('Профиль обновлён — гости увидят новые данные.', 'good');
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  /* Сброс пароля кухне: администратор точки делает это сам. */
  var passwordButton = document.getElementById('kitchen-password');
  if (passwordButton) passwordButton.addEventListener('click', function () {
    var box = document.getElementById('kitchen-creds');
    EP.busy(passwordButton, 'Выдаём', async function () {
      try {
        var payload = await EP.apiFetch('/api/staff/kitchen-password', { method: 'POST' });
        box.hidden = false;
        box.innerHTML =
          '<div class="creds__head"><strong>Новый пароль кухни</strong>' +
            '<button class="link-btn link-btn--muted" type="button" id="kitchen-creds-close">' +
            'Скрыть</button></div>' +
          '<p class="creds__note">' + EP.escapeHtml(payload.message) + '</p>' +
          '<div class="creds__rows"><div class="creds__row">' +
            '<span class="creds__label">Логин кухни</span>' +
            '<code class="creds__login">' + EP.escapeHtml(payload.username) + '</code>' +
            '<code class="creds__password">' + EP.escapeHtml(payload.password) + '</code>' +
          '</div></div>';
        EP.nudge(box, 'enter');
        document.getElementById('kitchen-creds-close').addEventListener('click', function () {
          box.hidden = true;
        });
      } catch (error) {
        EP.say(error.message, 'bad');
      }
    });
  });

  document.getElementById('crew-out').addEventListener('click', function (event) {
    event.preventDefault();
    EP.apiFetch('/api/auth/logout', { method: 'POST' })
      .catch(function () { /* сессия и так истечёт */ })
      .then(function () { EP.go('/login'); });
  });

  /* ── Аналитика: два критерия успеха продукта ───────────────────────────── */

  var reportBody = document.getElementById('report-body');

  function goalMark(done) {
    return '<span class="report__goal report__goal--' + (done ? 'yes' : 'no') + '">' +
      (done ? 'цель достигнута' : 'цель пока нет') + '</span>';
  }

  function bar(value, limit) {
    var share = Math.min(Math.round(value / limit * 100), 100);
    return '<span class="report__bar"><span style="width:' + share + '%"></span></span>';
  }

  function paintReport(report) {
    if (!reportBody) return;
    var wait = report.average_wait_minutes || 0;
    var growth = report.throughput_growth_percent || 0;
    reportBody.innerHTML =
      '<article class="report__card">' +
        '<div class="report__label">Среднее ожидание</div>' +
        '<div class="report__value">' + wait + ' <small>мин</small></div>' +
        bar(wait, 40) +
        '<div class="report__note">Было ' + Math.round(report.baseline_wait_minutes) +
          ' мин, цель — 20 минут или меньше. ' + goalMark(report.wait_target_met) + '</div>' +
      '</article>' +
      '<article class="report__card">' +
        '<div class="report__label">Рост пропускной способности</div>' +
        '<div class="report__value">' + growth.toFixed(1) + ' <small>%</small></div>' +
        bar(Math.max(growth, 0), 50) +
        '<div class="report__note">Эталон — ' + report.baseline_orders_count +
          ' заказов за период. Цель — рост от 25%. ' +
          goalMark(growth >= 25) + '</div>' +
      '</article>' +
      '<article class="report__card">' +
        '<div class="report__label">Заказов принято</div>' +
        '<div class="report__value">' + report.orders_count + '</div>' +
        '<div class="report__note">Из них выдано: ' + report.picked_up_count +
          ' · не забрали: ' + report.lost_orders_count + '</div>' +
      '</article>' +
      '<article class="report__card">' +
        '<div class="report__label">Мощность кухни</div>' +
        '<div class="report__value">' + report.capacity_per_hour + ' <small>порций/час</small></div>' +
        '<div class="report__note">Период: ' + report.date_from + ' — ' + report.date_to + '</div>' +
      '</article>' +
      (report.message ? '<p class="muted small report__message">' + EP.escapeHtml(report.message) + '</p>' : '');
  }

  async function loadReport(period) {
    if (!reportBody) return;
    try {
      paintReport(await EP.apiFetch('/api/staff/analytics?period=' + period));
    } catch (error) {
      reportBody.innerHTML = '<p class="muted small">' + EP.escapeHtml(error.message) + '</p>';
    }
  }

  if (reportBody) {
    root.querySelectorAll('input[name="period"]').forEach(function (input) {
      input.addEventListener('change', function () { loadReport(input.value); });
    });
  }

  /* ── Запуск ────────────────────────────────────────────────────────────── */
  window.setInterval(tick, 1000);
  loadOrders();
  /* Очередь подтягивается сама: заказ гостя должен появиться на экране смены
     без перезагрузки, а смена статуса — сразу отразиться у гостя. В скрытой
     вкладке сервер не дёргаем. */
  window.setInterval(function () {
    if (document.hidden) return;
    loadOrders();
  }, 8000);
  showPanel('queue');
  window.addEventListener('resize', function () {
    var active = root.querySelector('.crew__tab.is-on');
    if (active) movePill(active);
  });
})();
