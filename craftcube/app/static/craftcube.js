/* CraftCube UI — replicates the essential elastic-skin behaviors:
   layout size classes, column navigation (#menu/#sidebar/#back),
   dark-mode toggle, message-list selection + toolbar enabling,
   popup menus, framed message preview. IDs/classes match what
   mail.html / message_part.html actually render. */
(function () {
  'use strict';

  // ------------------------------------------------------------ layout classes
  function layoutClass() {
    // Elastic breakpoints (ui.js screen_mode): phone <=480, small <=768,
    // normal <=1200, large >1200. `touch` mode is set at <=1024.
    var w = window.innerWidth;
    var mode = w <= 480 ? 'phone' : w <= 768 ? 'small' : w <= 1200 ? 'normal' : 'large';
    return 'layout-' + mode;
  }
  function applyLayout() {
    var c = layoutClass();
    var cls = document.documentElement.className
      .replace(/ ?layout-(phone|small|normal|large)/g, '');
    if (window.innerWidth <= 1024) { if (cls.indexOf('touch') < 0) cls += ' touch'; }
    else cls = cls.replace(/ ?touch/g, '');
    document.documentElement.className = (cls + ' ' + c).trim();
  }
  document.addEventListener('DOMContentLoaded', applyLayout);
  window.addEventListener('resize', applyLayout);

  // ui.js: buttons that should be hidden on small screen devices —
  // data-hidden="big|small|phone|large|lbs" becomes hidden-<mode> class
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-hidden]').forEach(function (el) {
      var v = el.getAttribute('data-hidden'), re = /(large|big|small|phone|lbs)/g, m,
        parent = el.parentElement && el.parentElement.tagName === 'LI' ? el.parentElement : el;
      while ((m = re.exec(v))) parent.classList.add('hidden-' + m[1]);
    });
  });

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
    initRefresh();
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

  // ------------------------------------------- dialog (app.js show_popup_dialog
  // + simple_dialog; jQuery-UI dialog DOM with Elastic's bootstrap_style)
  function ccDialog(content, title, opts) {
    opts = opts || {};
    var isIframe = content.tagName === 'IFRAME';
    var popup = document.createElement('div');
    popup.className = 'popup' + (isIframe ? ' iframe' : '');
    popup.appendChild(content);

    var overlay = document.createElement('div');
    overlay.className = 'ui-widget-overlay ui-front';
    overlay.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;z-index:100';

    var dlg = document.createElement('div');
    dlg.className = 'ui-dialog ui-widget ui-widget-content ui-front ui-draggable ui-resizable';
    dlg.setAttribute('role', 'dialog');
    dlg.setAttribute('aria-labelledby', 'cc-dialog-title');
    dlg.style.cssText = 'position:fixed;z-index:101;display:flex;flex-direction:column';

    var bar = document.createElement('div');
    bar.className = 'ui-dialog-titlebar ui-widget-header ui-corner-all ui-helper-clearfix';
    bar.innerHTML = '<span id="cc-dialog-title" class="ui-dialog-title">' + title + '</span>' +
      '<a href="#" role="button" class="ui-dialog-titlebar-close ui-corner-all" title="Close">' +
      '<span class="voice">Close</span></a>';
    dlg.appendChild(bar);
    dlg.appendChild(popup);

    function close() {
      dlg.remove();
      overlay.remove();
      if (opts.onclose) opts.onclose();
    }
    bar.querySelector('.ui-dialog-titlebar-close').addEventListener('click', function (e) {
      e.preventDefault(); close();
    });

    var buttons = opts.buttons || [{ label: 'Close', cls: 'cancel mainaction', click: close }];
    if (buttons.length) {
      var pane = document.createElement('div');
      pane.className = 'ui-dialog-buttonpane ui-widget-content ui-helper-clearfix';
      var set = document.createElement('div');
      set.className = 'ui-dialog-buttonset';
      buttons.forEach(function (b) {
        var el = document.createElement('button');
        el.type = 'button';
        // ui.js bootstrap_style(): btn + btn-primary for .mainaction, else btn-secondary
        var cls = 'btn ' + (b.cls || '');
        el.className = cls + (/mainaction|primary/.test(cls) ? ' btn-primary' : ' btn-secondary');
        el.textContent = b.label;
        el.addEventListener('click', function () { if (b.click) b.click(); });
        set.appendChild(el);
      });
      pane.appendChild(set);
      dlg.appendChild(pane);
    }

    // resizable grip (jQuery-UI resizable markup; Elastic themes .ui-icon.ui-resizable-se)
    var grip = document.createElement('span');
    grip.className = 'ui-resizable-handle ui-resizable-se ui-icon ui-icon-gripsmall-diagonal-se';
    grip.style.cssText = 'position:absolute;cursor:se-resize;width:12px;height:12px;right:1px;bottom:1px;z-index:2';
    dlg.appendChild(grip);
    grip.addEventListener('mousedown', function (e) {
      e.preventDefault();
      var h0 = dlg.offsetHeight, y0 = e.clientY;
      var move = function (ev) { dlg.style.height = Math.max(200, h0 + ev.clientY - y0) + 'px'; popup.style.height = Math.max(120, dlg.offsetHeight - (pane0 ? pane0.offsetHeight : 0) - bar.offsetHeight) + 'px'; };
      var up = function () { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
      var pane0 = dlg.querySelector('.ui-dialog-buttonpane');
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });

    // draggable titlebar (jQuery-UI draggable on .ui-dialog-titlebar)
    bar.style.cursor = 'default';
    bar.addEventListener('mousedown', function (e) {
      if (e.target.closest('.ui-dialog-titlebar-close')) return;
      var x0 = e.clientX, y0 = e.clientY, l0 = dlg.offsetLeft, t0 = dlg.offsetTop;
      var move = function (ev) { dlg.style.left = (l0 + ev.clientX - x0) + 'px'; dlg.style.top = (t0 + ev.clientY - y0) + 'px'; };
      var up = function () { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });

    document.body.appendChild(overlay);
    document.body.appendChild(dlg);

    // center like Elastic's dialog_open()
    var chrome = bar.offsetHeight + (dlg.querySelector('.ui-dialog-buttonpane') || { offsetHeight: 0 }).offsetHeight;
    var h = Math.min(opts.height || 400, window.innerHeight - 40 - chrome);
    var w = Math.min(opts.width || 500, window.innerWidth - 20);
    dlg.style.width = w + 'px';
    if (isIframe) { popup.style.height = h + 'px'; }
    if (window.innerWidth <= 480) {
      dlg.style.width = '100%'; dlg.style.height = '100%';
      dlg.style.left = '0'; dlg.style.top = '0';
    } else {
      dlg.style.top = Math.max(20, (window.innerHeight - dlg.offsetHeight) / 2) + 'px';
      dlg.style.left = Math.max(10, (window.innerWidth - w) / 2) + 'px';
    }
    var keyH = function (e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', keyH, true); }
    };
    document.addEventListener('keydown', keyH, true);
    return { dlg: dlg, popup: popup, close: close };
  }
  window.cc_simple_dialog = ccDialog;
  window.cc_iframe_dialog = function (src, title, height, opts) {
    opts = opts || {};
    var f = document.createElement('iframe');
    f.src = src;
    f.style.cssText = 'width:100%;height:100%;border:0';
    var d = ccDialog(f, title, { height: height || 400, buttons: opts.buttons,
                                 buttons_previous: opts.buttons_previous, onclose: opts.onclose });
    d.iframe = f;
    return d;
  };
  // ui.js about_dialog(): iframe of the framed about page in a dialog
  window.cc_about_dialog = function (elem) {
    cc_iframe_dialog('/about?_framed=1', elem.textContent.trim(), 400);
    return false;
  };
  // mail.js create-folder command: name prompt in a dialog, posted to the
  // folders action (reference uses a framed folder-edit form; a dialog form
  // is the closest static equivalent)
  window.cc_create_folder = function () {
    var form = document.createElement('form');
    form.method = 'post';
    form.action = location.pathname;
    form.className = 'propform';
    form.innerHTML = '<input type="hidden" name="_act" value="create">' +
      '<div class="formcontent"><div class="form-group row">' +
      '<label for="cc-newfolder" class="col-form-label col-sm-4">Folder name</label>' +
      '<div class="col-sm-8"><input type="text" name="name" id="cc-newfolder" class="form-control" required></div></div></div>';
    var inp = form.querySelector('input');
    var ref = cc_simple_dialog(form, 'Create folder', {
      width: 360,
      buttons: [
        { label: 'Create', cls: 'mainaction create', click: function () {
            if (inp.value.trim()) form.submit();
          } },
        { label: 'Cancel', cls: 'cancel', click: function () { dlg.close(); } },
      ]
    });
    var dlg = ref;
    inp.focus();
    return false;
  };

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
      // Reference semantics (ui.js): toolbar acts on the *selection*
      // (checkboxes or the clicked/.selected row), not on the merely
      // focused/previewed row (direct ?_uid= links mark rows 'focused' only).
      var ctx = toolbarContext();
      var hasSel = ctx.length > 0;
      document.body.classList.toggle('has-selection', hasSel);
      enabled('#tb-delete', hasSel);
      enabled('#tb-archive', hasSel);
      enabled('#markmessagemenulink', hasSel);
      // ui.js: the "More" menu is always enabled — it holds folder-level
      // actions (check mail, mark all read, ...), not just selection ones
      enabled('#messagemenulink', true);
      enabled('#tb-reply', ctx.length === 1);
      enabled('#tb-replyall, #replyall-menu a[data-mode], #replyallmenulink', ctx.length === 1);
      enabled('#tb-forward, #forward-menu a[data-mode], #forwardmenulink', ctx.length === 1);
      enabled('#message-menu a', hasSel);
      enabled('#download-menu a', hasSel);
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
        // "Open in new window" has no static href in list view: point it at
        // the message view of the current selection
        var extwin = document.querySelector('#tb-extwin');
        if (extwin) {
          var base = (extwin.getAttribute('href') || '#').split('?')[0];
          if (base === '#') extwin.setAttribute('href', '/message?' + q);
        }
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
          if (uids.length && confirm('Really delete the selected message(s)?')) {
            var extra = {};
            var sel = document.querySelector('#messagelist tr.selected');
            if (sel) extra._return_uid = sel.getAttribute('data-uid') || '';
            act('delete', uids, extra);
          }
        } else if (cmd === 'archive') {
          act('archive', toolbarContext(), {});
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
      if (!uids.length && ['empty', 'markallread', 'compact'].indexOf(command) < 0) return;
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

    // list-options popup applies sort/order/list-mode
    window.cc_apply_list_options = function () {
      var col = document.getElementById('listoptions-sortcol').value;
      var ord = document.getElementById('listoptions-sortord').value.toLowerCase();
      var modeSel = document.getElementById('listoptions-threads');
      var url = new URL(location.href);
      url.searchParams.set('_sort', col);
      url.searchParams.set('_sort_order', ord);
      if (modeSel) url.searchParams.set('_mode', modeSel.value);
      url.searchParams.delete('_page');
      location.href = url.toString();
    };

    // search-modifier sublists (Sender/Recipient expand to fine-grained fields)
    document.querySelectorAll('#searchmenu li.with-sublist > a.dropdown').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var sub = a.parentElement.querySelector('ul.proplist');
        if (sub) sub.classList.toggle('d-none');
      });
    });

    // Import uploadform: picking a file submits immediately (like Elastic)
    document.querySelectorAll('#uploadform input.local-upload').forEach(function (inp) {
      inp.addEventListener('change', function () {
        if (inp.files && inp.files.length) inp.form.submit();
      });
    });

    // Download... submenu (zipdownload): build export URL for current selection
    document.querySelectorAll('#download-menu a[data-dlfmt]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var uids = toolbarContext();
        if (!uids.length) return;
        var url = '/message/export?_mbox=' + encodeURIComponent(boxOf(uids[0])) +
                  '&_format=' + a.getAttribute('data-dlfmt');
        uids.forEach(function (u) { url += '&_uids[]=' + u; });
        location.href = url;
        window.cc_close_popups();
      });
    });

    // Threads popup: expand unread / all / collapse all — client-side, like Elastic
    function setThreadState(mode) {
      var roots = rows().filter(function (r) { return r.getAttribute('data-depth') === '0'; });
      roots.forEach(function (root) {
        var hide = false;
        var sib = root.nextElementSibling;
        while (sib && sib.getAttribute('data-depth') !== null && sib.getAttribute('data-depth') !== '0') {
          if (mode === 'all') sib.style.display = '';
          else if (mode === 'none') sib.style.display = 'none';
          else if (mode === 'unread') {
            if (!hide && sib.classList.contains('unread')) sib.style.display = '';
            else { sib.style.display = 'none'; hide = true; }
          }
          sib = sib.nextElementSibling;
        }
      });
    }
    document.querySelectorAll('#threadselect-menu a[data-thread]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        setThreadState(a.getAttribute('data-thread'));
        window.cc_close_popups();
      });
    });

    // 'Expand message threads' preference: 0 never, 1 all, 2 only unread
    var aet = document.body.getAttribute('data-autoexpand-threads');
    if (aet === '1') setThreadState('all');
    else if (aet === '2') setThreadState('unread');

    // 'Mark messages as read' preference: mark seen N seconds after preview
    function scheduleRead() {
      var frame = document.getElementById('messagecontframe');
      if (!frame) return;
      var rt = parseInt(frame.getAttribute('data-read-time') || '0', 10);
      var sel = document.querySelector('#messagelist tr.selected');
      if (rt <= 0 || !sel || !sel.classList.contains('unread')) return;
      var uid = sel.getAttribute('data-uid') || (sel.querySelector('input[name=_uids[]]') || {}).value;
      var mbox = frame.getAttribute('data-folder');
      clearTimeout(scheduleRead._t);
      scheduleRead._t = setTimeout(function () {
        var fd = new FormData();
        fd.append('_mbox', mbox); fd.append('_act', 'read'); fd.append('_uids[]', uid);
        fetch('/mail/act', { method: 'POST', body: fd })
          .then(function () { sel.classList.remove('unread'); });
      }, rt * 1000);
    }
    document.querySelectorAll('#messagelist tr.message').forEach(function (r) {
      r.addEventListener('click', function () { setTimeout(scheduleRead, 300); });
    });
    scheduleRead();

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

  // ------------------------------------------------- recipient-input widgets
  // ui.js recipient_input(): To/Cc/Bcc/Reply-To/Followup-To render as a chip
  // list; the original input/textarea is hidden and keeps the posted value
  // ("Name <a@b>, <c@d>, "). Enter/comma/blur commits, Backspace removes the
  // last chip, clicks on a chip's x remove it.
  (function () {
    window.cc_recipient_add = {};
    var SELS = ['#compose_to textarea[name="_to"]', '#compose_cc textarea[name="_cc"]',
                '#compose_bcc textarea[name="_bcc"]',
                '#compose_replyto input[name="_reply_to"]',
                '#compose_followupto input[name="_followup_to"]'];
    function split_addr(v) {
      var out = [], depth = 0, cur = '';
      for (var i = 0; i < v.length; i++) {
        var ch = v[i];
        if (ch === '<') depth++;
        if (ch === '>') depth--;
        if (ch === ',' && depth === 0) { out.push(cur); cur = ''; }
        else cur += ch;
      }
      out.push(cur);
      return out.map(function (s) { return s.trim(); }).filter(Boolean);
    }
    function fmt(a) {
      var m = a.match(/^(.*?)<([^>]+)>\s*$/);
      if (m) return { name: m[1].trim().replace(/^"|"$/g, ''), email: m[2].trim(), full: true };
      return { name: a, email: '', full: false };
    }
    SELS.forEach(function (sel) {
      var field = document.querySelector(sel);
      if (!field || field.hasAttribute('data-recipient-input-done')) return;
      field.setAttribute('data-recipient-input', 'true');
      field.setAttribute('data-recipient-input-done', '1');
      field.style.cssText = 'position: absolute; opacity: 0; left: -5000px; width: 10px;';
      var input_group = field.closest('.input-group');
      var ul = document.createElement('ul');
      ul.className = 'form-control recipient-input ac-input rounded-left ui-sortable';
      ul.setAttribute('role', 'listbox');
      ul.innerHTML = '<li class="input"><input type="text" tabindex="' +
        (field.getAttribute('tabindex') || '1') + '" autocomplete="off" aria-autocomplete="list" aria-expanded="false" role="combobox"></li>';
      field.parentNode.insertBefore(ul, field.nextSibling);
      var inp = ul.querySelector('li.input input');
      function add(a, seed) {
        a = a.trim().replace(/,+$/, '');
        if (!a) return;
        var f = fmt(a);
        var li = document.createElement('li');
        li.className = 'recipient';
        if (f.full) li.setAttribute('title', a);
        li.innerHTML = '<span class="name"></span><span class="email"></span>' +
          '<a class="button icon remove"></a>';
        li.querySelector('.name').textContent = f.name;
        li.querySelector('.email').textContent = f.full ? ' <' + f.email + '>,' : ',';
        li.querySelector('a').addEventListener('click', function (e) {
          e.preventDefault(); li.remove(); rebuild();
        });
        li.addEventListener('click', function (e) {
          // ui.js: click a chip to edit it back into the input
          if (e.target.tagName === 'A') return;
          inp.value = chip_addr(li);
          li.remove(); rebuild(); inp.focus();
        });
        ul.insertBefore(li, ul.querySelector('li.input'));
        if (!seed) rebuild();
        inp.value = '';
      }
      function chip_addr(li) {
        var name = li.querySelector('.name').textContent;
        var email = li.querySelector('.email').textContent.replace(/,+$/, '').trim();
        if (email.charAt(0) === '<' && email.charAt(email.length - 1) === '>') {
          email = email.slice(1, -1).trim();
        }
        if (email && name && name !== email) return name + ' <' + email + '>';
        return name || email;
      }
      function rebuild() {
        // re-derive the textarea value from the remaining chips
        // (reference: "Name <a@b>," + "<c@d>," with no separator space)
        var parts = [];
        ul.querySelectorAll('li.recipient').forEach(function (li) {
          parts.push(chip_addr(li) + ',');
        });
        field.value = parts.join('');
      }
      // initial chips from prefilled value, then normalize the value
      split_addr(field.value).forEach(function (a) { add(a, true); });
      rebuild();
      window.cc_recipient_add[field.name] = add;
      window.cc_recipient_add[field.id] = add;
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          if (inp.value.trim()) add(inp.value);
        } else if (e.key === 'Backspace' && !inp.value) {
          var chips = ul.querySelectorAll('li.recipient');
          if (chips.length) { chips[chips.length - 1].remove(); rebuild(); }
        }
      });
      inp.addEventListener('blur', function () {
        if (inp.value.trim()) add(inp.value);
      });
      input_group.addEventListener('mousedown', function (e) {
        if (!e.target.closest('a')) setTimeout(function () { inp.focus(); ul.classList.add('focus'); }, 0);
      });
      inp.addEventListener('focus', function () { ul.classList.add('focus'); });
      inp.addEventListener('blur', function () { ul.classList.remove('focus'); });
      if (field.autofocus) inp.focus();
      // keep the textarea authoritative when the form posts
      field.form && field.form.addEventListener('submit', rebuild);
    });
  })();

  // ------------------------------------------------- page jumper (ui.js goto)
  // Enter in the pager input navigates to the typed page number.
  document.querySelectorAll('input.rcpagejumper').forEach(function (inp) {
    inp.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      var page = parseInt(inp.value, 10);
      if (!page) return;
      var url = new URL(window.location.href);
      url.searchParams.set('_page', page);
      window.location.href = url.toString();
    });
  });

  // ----------------------------------------------- listing rows with data-href
  // (Elastic navigates list rows via JS; e.g. Settings > Preferences sections)
  document.querySelectorAll('tr[data-href], li[data-href]').forEach(function (row) {
    function go() { location.href = row.getAttribute('data-href'); }
    row.addEventListener('click', function (e) {
      if (e.target.closest('a, input, button')) return;
      go();
    });
    row.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') go();
    });
  });

  // ------------------------------- rows opening a section in a local frame
  // (ui.js: clicking a settings section row loads the form into
  //  #preferences-frame and marks the row selected, URL unchanged)
  document.querySelectorAll('tr[data-framed-href], li[data-framed-href]').forEach(function (row) {
    function go() {
      var frame = document.getElementById('preferences-frame');
      if (!frame) return;
      var table = row.closest('table, ul');
      if (table) table.querySelectorAll('.selected').forEach(function (el) {
        el.classList.remove('selected', 'focused');
        el.setAttribute('aria-selected', 'false');
      });
      row.classList.add('selected', 'focused');
      row.setAttribute('aria-selected', 'true');
      frame.src = row.getAttribute('data-framed-href');
    }
    row.addEventListener('click', function (e) {
      if (e.target.closest('a, input, button')) return;
      go();
    });
    row.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') go();
    });
  });

  // --------------------------------------------------- empty-list info message
  // (ui.js: data-label-msg/-ext/-create-command -> div.listing-info)
  document.querySelectorAll('table[data-label-msg], ul[data-label-msg]').forEach(function (table) {
    var info = document.createElement('div');
    info.className = 'listing-info hidden';
    table.parentNode.insertBefore(info, table.nextSibling);
    var list = table.tagName === 'UL' ? table : table.querySelector('tbody') || table;
    if (!list.querySelector('tr,li')) {
      var msg = table.getAttribute('data-label-msg');
      var ext = table.getAttribute('data-label-ext');
      if (ext) msg += ' ' + ext;
      info.textContent = msg;
      info.classList.remove('hidden');
    }
  });

  // ------------------------------------------------------------ auto refresh
  function initRefresh() {
    var mins = parseInt(document.body.getAttribute('data-refresh-interval') || '0', 10);
    if (!mins || !document.getElementById('messagelist')) return;
    setTimeout(function () {
      var url = new URL(location.href);
      url.searchParams.delete('_uid'); // don't steal focus back to the preview
      location.href = url.toString();
    }, mins * 60000);
  }

  // --------------------------------------------- recipient_selector (ui.js):
  // "Add contact" opens the contacts list in a dialog; Insert appends the
  // selected addresses to the recipient field, comma-separated
  window.cc_recipient_dialog = function (field) {
    var d = cc_iframe_dialog('/contacts?_dialog=1&_source=0', 'Insert contact(s)', 600, {
      buttons: [
        { label: 'Insert', cls: 'insert recipient mainaction',
          click: function () {
            try { d.iframe.contentWindow.cc_recipient_insert(); } catch (e) {}
          } },
        { label: 'Cancel', cls: 'cancel', click: function () { d.close(); } }
      ]
    });
    window.cc_recipient_done = function (list) {
      var add = window.cc_recipient_add && window.cc_recipient_add[field];
      var ta = document.getElementById(field);
      if (list && list.length) {
        list.forEach(function (r) {
          var a = r.name && r.name !== r.email ? r.name + ' <' + r.email + '>' : r.email;
          if (add) add(a);
          else if (ta) {
            var have = ta.value.trim() ? ta.value.trim().split(/\s*,\s*/) : [];
            if (have.indexOf(a) < 0) ta.value = (ta.value.trim() ? ta.value.trim() + ', ' : '') + a;
          }
        });
      }
      d.close();
    };
    return false;
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
