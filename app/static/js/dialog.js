/* Единые диалоги: на телефоне выезжают снизу, на компьютере — по центру. Esc и тап по фону закрывают. */
(function () {
  'use strict';
  var stack = [];

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  /* opts: icon (эмодзи), title, text, code (крупный номер), steps [строки], actions [{label, kind, onClick}] */
  function open(opts) {
    var back = el('div', 'dlg');
    var box = el('div', 'dlg__box');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    var html = '';
    if (opts.icon) html += '<div class="dlg__icon" aria-hidden="true">' + opts.icon + '</div>';
    html += '<h2 class="dlg__title">' + esc(opts.title || '') + '</h2>';
    if (opts.text) html += '<p class="dlg__text">' + esc(opts.text) + '</p>';
    if (opts.code) html += '<div class="dlg__code">' + esc(opts.code) + '</div>';
    if (opts.steps) {
      html += '<ol class="dlg__steps">' + opts.steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') + '</ol>';
    }
    box.innerHTML = html;
    var row = el('div', 'dlg__actions');
    (opts.actions || [{ label: 'Понятно', kind: 'primary' }]).forEach(function (a) {
      var b = el('button', 'btn ' + (a.kind === 'ghost' ? 'btn--line' : a.kind === 'danger' ? 'btn--line dlg__danger' : 'btn--flame'));
      b.type = 'button';
      b.textContent = a.label;
      b.addEventListener('click', function () { close(a.onClick); });
      row.appendChild(b);
    });
    box.appendChild(row);
    back.appendChild(box);

    var prev = document.activeElement;
    function close(after) {
      var i = stack.indexOf(api); if (i > -1) stack.splice(i, 1);
      back.classList.add('is-out');
      window.setTimeout(function () { back.remove(); if (prev && prev.focus) try { prev.focus(); } catch (_) {} }, 180);
      document.removeEventListener('keydown', onKey);
      if (typeof after === 'function') after();
      if (typeof opts.onClose === 'function') opts.onClose();
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(back);
    window.requestAnimationFrame(function () { back.classList.add('is-in'); });
    var first = box.querySelector('button'); if (first) first.focus();
    var api = { close: close };
    stack.push(api);
    return api;
  }

  /* Вопрос «да/нет» вместо серого окна браузера. */
  function confirm(o) {
    return new Promise(function (resolve) {
      var answered = false;
      open({
        icon: o.icon, title: o.title, text: o.text,
        actions: [
          { label: o.ok || 'Да', kind: o.danger ? 'danger' : 'primary', onClick: function () { answered = true; resolve(true); } },
          { label: o.cancel || 'Отмена', kind: 'ghost', onClick: function () { answered = true; resolve(false); } }
        ],
        onClose: function () { if (!answered) resolve(false); }
      });
    });
  }

  window.EPDialog = { open: open, confirm: confirm, isOpen: function () { return stack.length > 0; } };
})();
