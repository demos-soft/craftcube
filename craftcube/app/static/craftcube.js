/* CraftCube UI — replicates the essential elastic-skin behaviors:
   layout size classes, column navigation (#menu/#sidebar/#back),
   dark-mode toggle, message-list selection + toolbar enabling. */
(function () {
  'use strict';

  // ------------------------------------------------------------ layout classes
  function layoutClass() {
    var w = window.innerWidth;
    if (w <= 480) return 'layout-phone';
    if (w <= 768) return 'layout-small';
    if (w <= 1024) return 'layout-normal';
    return 'layout-large';
  }
  function applyLayout() {
    var c = layoutClass();
    document.documentElement.className = document.documentElement.className
      .replace(/layout-(phone|small|normal|large)/g, '').trim() + ' ' + c;
    updateColumns();
  }

  // ------------------------------------------------------------ column nav
  var cols = ['layout-menu', 'layout-sidebar', 'layout-list', 'layout-content'];
  function visibleColumn() {
    for (var i = cols.length - 1; i >= 0; i--) {
      var el = document.getElementById(cols[i]);
      if (el && el.classList.contains('selected')) return cols[i];
    }
    return 'layout-list';
  }
  function selectColumn(id) {
    cols.forEach(function (c) {
      var el = document.getElementById(c);
      if (el) el.classList.toggle('selected', c === id ||
        (c === 'layout-menu' && document.documentElement.classList.contains('layout-phone') === false && false));
    });
    var m = document.getElementById('layout-menu');
    if (m && id === 'layout-menu') m.classList.add('selected');
  }
  function updateColumns() {
    // On small screens only one column shows; keep the selected one visible.
    var small = window.innerWidth <= 1024;
    document.querySelectorAll('#layout > div').forEach(function (el) {
      if (!small) el.classList.remove('hidden-col');
    });
  }
  window.addEventListener('resize', applyLayout);
  document.addEventListener('DOMContentLoaded', function () {
    applyLayout();
    window.addEventListener('hashchange', onHash);
    onHash();
    initList();
    initStack();
  });
  function onHash() {
    var h = location.hash.replace('#', '');
    if (['menu', 'sidebar', 'list', 'content', 'back'].indexOf(h) < 0) return;
    var map = { menu: 'layout-menu', sidebar: 'layout-sidebar', list: 'layout-list', content: 'layout-content' };
    if (h === 'back') {
      // go back one level: content->list->sidebar
      var cur = visibleColumn();
      var idx = cols.indexOf(cur);
      selectColumn(cols[Math.max(0, idx - 1)]);
    } else {
      selectColumn(map[h]);
    }
    history.replaceState(null, '', location.pathname + location.search);
  }

  // ------------------------------------------------------------ dark mode
  document.addEventListener('DOMContentLoaded', function () {
    var t = document.getElementById('darktoggle');
    function label() {
      if (!t) return;
      var dark = document.documentElement.classList.contains('dark-mode');
      t.textContent = dark ? 'Light' : 'Dark';
    }
    label();
    if (t) t.addEventListener('click', function (e) {
      e.preventDefault();
      var dark = document.documentElement.classList.toggle('dark-mode');
      document.cookie = 'colorMode=' + (dark ? 'dark' : 'light') + ';path=/;max-age=31536000';
      label();
    });
  });

  // ------------------------------------------------------------ message list
  function initList() {
    var list = document.getElementById('messagelist');
    if (!list) return;
    var folder = document.querySelector('input[name=_mbox]');
    var mbox = folder ? folder.value : 'INBOX';

    // select-all checkbox
    var checkall = document.getElementById('checkall');
    if (checkall) checkall.addEventListener('click', function () {
      list.querySelectorAll('tbody input[type=checkbox]').forEach(function (cb) {
        cb.checked = checkall.checked;
      });
      updateToolbar();
    });
    list.addEventListener('change', function (e) {
      if (e.target.type === 'checkbox') updateToolbar();
    });
    list.addEventListener('click', function (e) {
      var tr = e.target.closest('tr.message');
      if (!tr || e.target.tagName === 'A' || e.target.type === 'checkbox') return;
      list.querySelectorAll('tr.selected').forEach(function (r) { r.classList.remove('selected'); });
      tr.classList.add('selected');
      var cb = tr.querySelector('input[type=checkbox]');
      if (cb) cb.checked = true;
      updateToolbar();
    });

    function selectedUids() {
      return Array.prototype.map.call(
        list.querySelectorAll('tbody input[type=checkbox]:checked'), function (cb) { return cb.value; });
    }
    function enabled(sel, on) {
      var el = document.querySelector(sel);
      if (!el) return;
      el.classList.toggle('disabled', !on);
    }
    function updateToolbar() {
      var n = selectedUids().length;
      enabled('#tb-delete', n > 0);
      enabled('#tb-markread', n > 0);
      enabled('#tb-markunread', n > 0);
      enabled('#tb-flag', n > 0);
      var sel = document.querySelector('tr.message.selected');
      var uid = sel ? sel.getAttribute('data-uid') : (n === 1 ? selectedUids()[0] : null);
      enabled('#tb-reply', !!uid);
      enabled('#tb-replyall', !!uid);
      enabled('#tb-forward', !!uid);
      if (uid) {
        var c = document.querySelector('#taskmenu a.compose') || document.querySelector('a.compose');
        var base = c ? c.getAttribute('href') : '/compose';
        if (base.indexOf('?') < 0) base += '?';
        document.getElementById('tb-reply').href = base + '&_mode=reply&_mbox=' + encodeURIComponent(mbox) + '&_uid=' + uid;
        document.getElementById('tb-replyall').href = base + '&_mode=replyall&_mbox=' + encodeURIComponent(mbox) + '&_uid=' + uid;
        document.getElementById('tb-forward').href = base + '&_mode=forward&_mbox=' + encodeURIComponent(mbox) + '&_uid=' + uid;
      }
    }

    // flag links and delete act via the hidden form
    document.querySelectorAll('#mailtoolbar a[data-act]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        act(a.getAttribute('data-act'));
      });
    });
    var del = document.getElementById('tb-delete');
    if (del) del.addEventListener('click', function (e) {
      e.preventDefault();
      if (del.classList.contains('disabled')) return;
      if (confirm('Really delete the selected message(s)?')) act('delete');
    });
    function act(command) {
      var form = document.getElementById('mailact');
      if (!form) return;
      var uids = selectedUids();
      if (!uids.length) {
        // fall back to the selected row (preview message)
        var sel = list.querySelector('tr.message.selected');
        if (sel) uids = [sel.getAttribute('data-uid')];
      }
      if (!uids.length) return;
      form.querySelectorAll('.act-uid').forEach(function (x) { x.remove(); });
      uids.forEach(function (u) {
        var i = document.createElement('input');
        i.type = 'hidden'; i.name = '_uids[]'; i.value = u; i.className = 'act-uid';
        form.appendChild(i);
      });
      var h = document.createElement('input');
      h.type = 'hidden'; h.name = '_act'; h.value = command; h.className = 'act-uid';
      form.appendChild(h);
      form.submit();
    }

    // clicking a message row loads it into the preview iframe
    list.addEventListener('click', function (e) {
      var a = e.target.closest('td.subject a');
      if (!a) return;
      var url = a.getAttribute('href');
      if (!url || url.indexOf('framed') > -1) return;
      var frame = document.getElementById('messagecontframe');
      if (frame) {
        e.preventDefault();
        frame.src = url + (url.indexOf('?') > -1 ? '&' : '?') + '_framed=1';
        document.getElementById('layout-content').classList.add('selected');
        list.querySelectorAll('tr.selected').forEach(function (r) { r.classList.remove('selected'); });
        var tr = a.closest('tr');
        tr.classList.add('selected');
        // mark icon read locally
        var icon = tr.querySelector('.msgicon.status');
        if (icon) icon.classList.remove('unread');
        tr.classList.remove('unread');
        updateToolbar();
        // and update the row href so plain links stay consistent
        if (window.innerWidth <= 1024) location.href = url;
      }
    });
    updateToolbar();
  }

  // ------------------------------------------------------------ message stack
  function initStack() {
    var stack = document.getElementById('messagestack');
    if (!stack) return;
    stack.querySelectorAll('.alert').forEach(function (el) {
      setTimeout(function () {
        el.style.transition = 'opacity .5s';
        el.style.opacity = '0';
        setTimeout(function () { el.remove(); }, 600);
      }, 5000);
    });
  }
})();
