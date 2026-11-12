/* CraftCube UI — replicates the essential elastic-skin behaviors:
   layout size classes, column navigation (#menu/#sidebar/#back),
   dark-mode toggle, message-list selection + toolbar enabling,
   popup menus, framed message preview. IDs/classes match what
   mail.html / message_part.html actually render. */
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
    var cls = document.documentElement.className
      .replace(/ ?layout-(phone|small|normal|large)/g, '');
    document.documentElement.className = (cls + ' ' + c).trim();
  }
  document.addEventListener('DOMContentLoaded', applyLayout);
  window.addEventListener('resize', applyLayout);

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
      if (el) el.classList.toggle('selected', c === id);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyLayout();
    if (document.getElementById('layout')) {
      window.addEventListener('hashchange', onHash);
      onHash();
    }
    initPopups();
    initList();
    initStack();
  });
  function onHash() {
    var h = location.hash.replace('#', '');
    if (['menu', 'sidebar', 'list', 'content', 'back'].indexOf(h) < 0) return;
    var map = { menu: 'layout-menu', sidebar: 'layout-sidebar', list: 'layout-list', content: 'layout-content' };
    if (h === 'back') {
      // go back one level: content->list->sidebar
      var idx = cols.indexOf(visibleColumn());
      selectColumn(cols[Math.max(0, idx - 1)]);
    } else {
      selectColumn(map[h]);
    }
    history.replaceState(null, '', location.pathname + location.search);
  }

  // ------------------------------------------------------------ dark mode
  document.addEventListener('DOMContentLoaded', function () {
    var t = document.getElementById('darktoggle');
    if (!t) return;
    function label() {
      var dark = document.documentElement.classList.contains('dark-mode');
      var inner = t.querySelector('.inner');
      if (inner) inner.textContent = dark ? 'Light mode' : 'Dark mode';
    }
    label();
    t.addEventListener('click', function (e) {
      e.preventDefault();
      var dark = document.documentElement.classList.toggle('dark-mode');
      document.cookie = 'colorMode=' + (dark ? 'dark' : 'light') + ';path=/;max-age=31536000';
      label();
    });
  });

  // ------------------------------------------------------------ popup menus
  function initPopups() {
    var open = null;
    function close() {
      if (open) {
        open.classList.remove('open');
        if (open.classList.contains('searchoptions')) open.classList.add('hidden');
        open.style.position = ''; open.style.top = ''; open.style.left = '';
        open = null;
      }
    }
    document.addEventListener('click', function (e) {
      var trig = e.target.closest('[data-popup]');
      if (trig) {
        e.preventDefault();
        var menu = document.getElementById(trig.getAttribute('data-popup'));
        if (!menu) return;
        if (open === menu) { close(); return; }
        close();
        open = menu;
        menu.classList.remove('hidden');
        menu.classList.add('open');
        // inline panels (search options) expand in place; menus float
        if (!menu.classList.contains('searchoptions')) {
          var r = trig.getBoundingClientRect();
          menu.style.position = 'fixed';
          menu.style.top = (r.bottom + 4) + 'px';
          menu.style.left = Math.max(4, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
          menu.style.zIndex = 200;
        }
        return;
      }
      if (!e.target.closest('.popupmenu.open')) close();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    window.cc_close_popups = close;
  }

  // ------------------------------------------------------------ message list
  function initList() {
    var list = document.getElementById('messagelist');
    if (!list) return;
    var mbox = list.getAttribute('data-folder') || 'INBOX';
    var actForm = document.getElementById('mailact');

    function rows() {
      return Array.prototype.slice.call(list.querySelectorAll('tbody tr.message'));
    }
    function checkedRow(r) {
      var cb = r.querySelector('td.selection input');
      return cb && cb.checked;
    }
    function selectedUids() {
      return rows().filter(checkedRow).map(function (r) { return r.getAttribute('data-uid'); });
    }
    function toolbarContext() {
      // selection first; fall back to the single previewed/selected row
      var uids = selectedUids();
      if (!uids.length) {
        var sel = list.querySelector('tr.message.selected');
        if (sel) uids = [sel.getAttribute('data-uid')];
      }
      return uids;
    }
    function boxOf(uid) {
      var tr = list.querySelector('tr.message[data-uid="' + uid + '"]');
      return tr ? (tr.getAttribute('data-box') || mbox) : mbox;
    }
    function enabled(sel, on) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.classList.toggle('disabled', !on);
      });
    }
    function updateToolbar() {
      var ctx = toolbarContext();
      enabled('#tb-delete', ctx.length > 0);
      enabled('#markmessagemenulink', ctx.length > 0);
      enabled('#messagemenulink', ctx.length > 0);
      enabled('#tb-reply', ctx.length === 1);
      enabled('#tb-replyall, #replyall-menu a[data-mode]', ctx.length === 1);
      enabled('#tb-forward, #forward-menu a[data-mode]', ctx.length === 1);
      enabled('#message-menu a', ctx.length > 0);
      if (ctx.length === 1) {
        var uid = ctx[0];
        var q = '_mbox=' + encodeURIComponent(boxOf(uid)) + '&_uid=' + uid;
        // reply/forward/edit links point at /compose?_mode=...; append context
        document.querySelectorAll(
            '#mailtoolbar a[href*="compose"], #forward-menu a[data-mode], ' +
            '#replyall-menu a[data-mode], #message-menu a[data-mode]')
          .forEach(function (a) {
            var href = a.getAttribute('href') || '';
            if (href.indexOf('compose') < 0) return;
            href = href.replace(/([?&])_mbox=[^&]*/g, '$1').replace(/([?&])_uid=[^&]*/g, '$1')
                       .replace(/[?&]+$/, '').replace(/\?&/, '?');
            href += (href.indexOf('?') < 0 ? '?' : '&') + q;
            a.setAttribute('href', href);
          });
        // direct message actions (print/export/source) point at the viewed message
        ['#tb-print', '#tb-export', '#tb-source'].forEach(function (idSel) {
          var a = document.querySelector(idSel);
          if (!a) return;
          var base = (a.getAttribute('href') || '#').split('?')[0];
          if (base !== '#') a.setAttribute('href', base + '?' + q);
        });
      }
    }

    // selection column toggle (stock: rcmail.enable_selection)
    var toggle = document.getElementById('list-toggle-button');
    if (toggle) toggle.addEventListener('click', function (e) {
      e.preventDefault();
      var on = list.classList.toggle('selection');
      document.querySelectorAll('#listselect-menu a[data-select]').forEach(function (el) {
        el.classList.toggle('disabled', !on);
      });
      if (!on) rows().forEach(function (r) {
        var cb = r.querySelector('td.selection input');
        if (cb) cb.checked = false;
      });
      updateToolbar();
      window.cc_close_popups();
    });

    // select-menu actions
    document.querySelectorAll('#listselect-menu a[data-select]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var mode = a.getAttribute('data-select');
        rows().forEach(function (r) {
          var cb = r.querySelector('td.selection input');
          if (!cb) return;
          if (mode === 'all' || mode === 'page') cb.checked = true;
          else if (mode === 'unread') cb.checked = r.classList.contains('unread');
          else if (mode === 'flagged') cb.checked = r.classList.contains('flagged');
          else if (mode === 'invert') cb.checked = !cb.checked;
          else if (mode === 'none') cb.checked = false;
        });
        updateToolbar();
        window.cc_close_popups();
      });
    });

    // interactions: flag toggle / subject preview / selection
    list.addEventListener('change', function (e) {
      if (e.target.type === 'checkbox') updateToolbar();
    });
    list.addEventListener('click', function (e) {
      var flag = e.target.closest('td.flags span.flag span[data-uid]');
      if (flag) {
        e.preventDefault();
        e.stopPropagation();
        act('flagtoggle', [flag.getAttribute('data-uid')],
            { _mbox_override: flag.getAttribute('data-box') || mbox });
        flag.classList.toggle('flagged');
        flag.classList.toggle('unflagged');
        return;
      }
      var a = e.target.closest('td.subject span.subject a');
      if (a) {
        var url = a.getAttribute('href');
        var frame = document.getElementById('messagecontframe');
        if (frame && window.innerWidth > 1024) {
          e.preventDefault();
          frame.src = url + (url.indexOf('?') > -1 ? '&' : '?') + '_framed=1';
          var content = document.getElementById('layout-content');
          if (content) content.classList.add('selected');
          rows().forEach(function (r) { r.classList.remove('selected'); });
          var tr = a.closest('tr');
          tr.classList.add('selected');
          var icon = tr.querySelector('.msgicon.status');
          if (icon) { icon.classList.remove('unread'); icon.title = ''; }
          tr.classList.remove('unread');
          updateToolbar();
        }
        return;
      }
      var tr2 = e.target.closest('tr.message');
      if (tr2 && list.classList.contains('selection')) {
        var cb2 = tr2.querySelector('td.selection input');
        if (cb2) { cb2.checked = !cb2.checked; updateToolbar(); }
      }
    });

    // toolbar/popup command links
    document.querySelectorAll('#mailtoolbar a[data-act], .popupmenu a[data-act]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var cmd = a.getAttribute('data-act');
        if (cmd === 'empty') {
          if (confirm('Really empty this folder?')) act('empty', [], {});
        } else if (cmd === 'markallread') {
          act('markallread', [], {});
        } else if (cmd === 'delete') {
          var uids = toolbarContext();
          if (uids.length && confirm('Really delete the selected message(s)?')) act('delete', uids, {});
        } else if (cmd === 'move' || cmd === 'copy') {
          act(cmd, toolbarContext(), { _dest: a.getAttribute('data-dest') });
        } else {
          act(cmd, toolbarContext(), {});
        }
        window.cc_close_popups();
      });
    });

    function act(command, uids, extra) {
      if (!actForm) return;
      if (!uids.length && ['empty', 'markallread'].indexOf(command) < 0) return;
      actForm.querySelectorAll('.act-field').forEach(function (x) { x.remove(); });
      function field(name, value) {
        if (value === undefined || value === null || value === '') return;
        var h = document.createElement('input');
        h.type = 'hidden'; h.name = name; h.value = value; h.className = 'act-field';
        actForm.appendChild(h);
      }
      uids.forEach(function (u) { field('_uids[]', u); });
      field('_act', command);
      // cross-folder actions (search across folders): map uid -> box
      if (uids.length) {
        var boxes = {};
        uids.forEach(function (u) { boxes[boxOf(u)] = true; });
        var names = Object.keys(boxes);
        if (names.length === 1) field('_mbox_override', names[0]);
        else if (names.length > 1)
          field('_box_map', uids.map(function (u) { return u + ':' + boxOf(u); }).join(','));
      }
      Object.keys(extra).forEach(function (k) { field(k, extra[k]); });
      actForm.submit();
    }

    // list-options popup applies sort/order
    window.cc_apply_list_options = function () {
      var col = document.getElementById('listoptions-sortcol').value;
      var ord = document.getElementById('listoptions-sortord').value.toLowerCase();
      var url = new URL(location.href);
      url.searchParams.set('_sort', col);
      url.searchParams.set('_sort_order', ord);
      url.searchParams.delete('_page');
      location.href = url.toString();
    };
    updateToolbar();
  }

  // summary/details label relayed from the preview iframe to the parent
  window.cc_set_summary_label = function (label) {
    if (window.parent !== window) {
      try {
        if (window.parent.cc_set_summary_label) {
          window.parent.cc_set_summary_label(label);
          return;
        }
      } catch (e) { /* cross-origin guard */ }
    }
    var el = document.querySelector('.details-toggle');
    if (el) el.textContent = label;
  };

  // ------------------------------------------------------------ message stack
  function initStack() {
    var stack = document.getElementById('messagestack');
    if (!stack) return;
    stack.querySelectorAll('.alert').forEach(function (el) {
      el.addEventListener('click', function () { el.remove(); });
      setTimeout(function () {
        el.style.transition = 'opacity .5s';
        el.style.opacity = '0';
        setTimeout(function () { el.remove(); }, 600);
      }, 6000);
    });
  }
})();
