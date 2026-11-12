/* CraftCube UI — replicates the essential elastic-skin behaviors:
   layout size classes, column navigation (#menu/#sidebar/#back),
   dark-mode toggle, message-list selection + toolbar enabling,
   popup menus, framed message preview. IDs/classes match what
   mail.html / message_part.html actually render. */
(function () {
  'use strict';

  // ------------------------------------------------- layout engine (ui.js)
  // Ports Elastic's screen_mode()/screen_resize()/screen_resize_small_all()/
  // app_menu()/show_*/hide_content machinery: on phone/small only the last
  // selected pane is visible, the menu drawer is a .popover with an overlay,
  // floating action buttons are created on small screens, and header titles
  // are margin-balanced (screen_resize_headers).
  var mode = 'large'; var touch = false;
  var panes = {};
  function pane(id) { return document.getElementById(id); }
  function computeScreenMode() {
    // ui.js screen_mode(): phone <=480, small <=768, normal <=1200, large
    var w = window.innerWidth;
    mode = w <= 480 ? 'phone' : w > 1200 ? 'large' : w > 768 ? 'normal' : 'small';
    touch = w <= 1024;
  }
  function applyLayout() {
    var cls = document.documentElement.className
      .replace(/ ?layout-(phone|small|normal|large)/g, '');
    if (touch) { if (cls.indexOf('touch') < 0) cls += ' touch'; }
    else cls = cls.replace(/ ?touch/g, '');
    document.documentElement.className = (cls + ' layout-' + mode).trim();
  }
  function show(el, on) { if (el) el.classList.toggle('hidden', !on); }
  var last_selected = null;

  function appMenu(showIt) {
    var menu = pane('layout-menu');
    if (!menu) return;
    if (showIt) {
      if (mode === 'phone') {
        if (!document.getElementById('menu-overlay')) {
          var ov = document.createElement('div');
          ov.id = 'menu-overlay';
          ov.className = 'popover-overlay';
          ov.addEventListener('click', function () { appMenu(false); });
          document.body.appendChild(ov);
        }
        if (!menu.dataset.ccInit) {
          menu.dataset.ccInit = '1';
          menu.addEventListener('click', function (e) {
            if (mode === 'phone' && e.target.closest('a')) appMenu(false);
          });
        }
        menu.classList.add('popover');
        menu.classList.remove('hidden');
      } else {
        menu.classList.remove('hidden', 'popover');
      }
    } else {
      var o = document.getElementById('menu-overlay');
      if (o) o.remove();
      menu.classList.add('hidden');
      menu.classList.remove('popover');
    }
  }

  function smallNone() {
    // hide back-list buttons except those living inside the sidebar
    document.querySelectorAll('a.back-list-button').forEach(function (b) {
      if (!b.closest('#layout-sidebar')) b.style.display = 'none';
    });
    // ui.js screen_resize_small_none: $('ul.menu.popupmenu').removeClass('popupmenu')
    document.querySelectorAll('ul.menu.popupmenu').forEach(function (u) {
      u.classList.remove('popupmenu');
    });
  }
  // ui.js screen_resize_small_all/normal: $('.header > ul.menu', layout.content
  // /layout.list).addClass('popupmenu') — the header toolbars become popups
  // on small screens so they never crowd the header buttons
  function popupHeaderMenus(onContent, onList) {
    if (onContent) {
      var c = pane('layout-content');
      if (c) {
        c.querySelectorAll(':scope > .header > ul.menu').forEach(function (u) {
          u.classList.add('popupmenu');
        });
      }
    }
    if (onList) {
      var l = pane('layout-list');
      if (l) {
        l.querySelectorAll(':scope > .header > ul.menu').forEach(function (u) {
          u.classList.add('popupmenu');
        });
      }
    }
  }
  function smallAll() {
    var got_content = false; var s;
    var content = pane('layout-content'); var list = pane('layout-list'); var sidebar = pane('layout-sidebar');
    if (content) {
      s = content === last_selected;
      content.classList.toggle('hidden', !s);
      got_content = s;
    }
    if (list) {
      s = !got_content && list === last_selected;
      list.classList.toggle('hidden', !s);
    }
    if (sidebar) {
      s = !got_content && (sidebar === last_selected || !list);
      sidebar.classList.toggle('hidden', !s);
    }
    if (got_content) {
      document.querySelectorAll('a.back-list-button').forEach(function (b) {
        if (!b.closest('#layout-sidebar')) b.style.display = '';
      });
    }
  }
  function screenResize() {
    var menu = pane('layout-menu'); var sidebar = pane('layout-sidebar');
      var list = pane('layout-list'); var content = pane('layout-content');
    if (mode === 'phone') { smallAll(); popupHeaderMenus(true, true); appMenu(false); }
    else if (mode === 'small') { smallAll(); popupHeaderMenus(true, true); appMenu(true); }
    else if (mode === 'normal') {
      var s;
      if (list) {
        s = list === last_selected ||
          (sidebar && last_selected !== sidebar && !sidebar.classList.contains('layout-sticky'));
        list.classList.toggle('hidden', !s);
      }
      if (sidebar) {
        s = !list || last_selected === sidebar || sidebar.classList.contains('layout-sticky');
        sidebar.classList.toggle('hidden', !s);
      }
      show(content, true);
      appMenu(true);
      smallNone();
      popupHeaderMenus(false, true);   // ui.js normal: only the list header menu collapses
    } else { // large
      [menu, sidebar, list, content].forEach(function (el) { if (el) el.classList.remove('hidden'); });
      smallNone();
      popupHeaderMenus(false, false);
    }
    screenResizeHeaders();
  }
  // ui.js screen_resize_headers(): balance .header-title margins so the
  // title stays centered between the header's left/right button groups.
  function screenResizeHeaders() {
    document.querySelectorAll('#layout > div > .header').forEach(function (hdr) {
      var title = null; var sizes = { left: 0, right: 0 };
      Array.prototype.forEach.call(hdr.children, function (ch) {
        if (ch.offsetParent === null || ch.classList.contains('position-absolute')) return;
        if (!title && ch.classList.contains('header-title')) { title = ch; return; }
        sizes[title ? 'right' : 'left'] += ch.offsetWidth;
      });
      if (!title) return;
      var right = 0; var left = 0;
      if (sizes.right >= sizes.left) { right = 0; left = sizes.right - sizes.left; }
      else { left = 0; right = sizes.left - sizes.right; }
      title.style.marginRight = right + 'px';
      title.style.marginLeft = left + 'px';
      title.style.paddingRight = '0px';
    });
  }
  // show/hide navigation used by the header buttons (ui.js show_content,
  // show_sidebar, show_list — these only rebalance headers, they do NOT
  // re-run screen_resize, which would undo the switch via last_selected)
  function showContent() {
    show(pane('layout-list'), false); show(pane('layout-sidebar'), false);
    var c = pane('layout-content'); show(c, true);
    var sb = pane('layout-sidebar'); if (sb) sb.classList.remove('layout-sticky');
    last_selected = c; screenResizeHeaders();
  }
  function showSidebar(sticky) {
    show(pane('layout-list'), false);
    var sb = pane('layout-sidebar'); show(sb, true);
    if (sticky) sb.classList.add('layout-sticky');
    if (mode === 'small' || mode === 'phone') show(pane('layout-content'), false);
    last_selected = sb; screenResizeHeaders();
  }
  function showList() {
    var list = pane('layout-list'); var sidebar = pane('layout-sidebar');
    if (!list && !sidebar) { history.back(); return; }
    if (sidebar) { sidebar.classList.add('hidden'); sidebar.classList.remove('layout-sticky'); }
    show(list, true);
    if (mode === 'small' || mode === 'phone') show(pane('layout-content'), false);
    last_selected = list; screenResizeHeaders();
  }

  // ui.js layout_init(): floating action buttons, small screens only
  function initFabs() {
    var list = pane('layout-list'); var content = pane('layout-content');
    if (!(list || content)) return;
    if (!(window.innerWidth <= 768)) return;   // is_mobile()
    var cls = document.body.className;
    var task = (cls.match(/task-([a-z-]+)/) || [])[1] || '';
    var action = (cls.match(/action-([a-z-]+)/) || [])[1] || 'none';
    var fabs = [];
    document.querySelectorAll('[data-fab]').forEach(function (button) {
      var t = button.getAttribute('data-fab-task') || '*';
        var a = button.getAttribute('data-fab-action') || '*';
      if ((t === '*' || t === task) &&
        (a === '*' || a === action || (a === 'none' && action === 'none'))) fabs.push(button);
    });
    if (!fabs.length) return;
    var wrap = document.createElement('div');
    wrap.className = 'floating-action-buttons';
    fabs.forEach(function (target) {
      // create_cloned_button(target, false, false, true)
      var clone = document.createElement('a');
      clone.className = target.className
        .replace(/btn-primary/g, 'primary').replace(/(btn[a-z-]*|button|disabled)/g, '').trim() + ' button';
      clone.href = '#';
      var inner = document.createElement('span');
      inner.className = 'inner';
      inner.textContent = target.textContent;
      clone.appendChild(inner);
      clone.addEventListener('click', function (e) {
        e.preventDefault();
        // the source may live in the hidden drawer: follow its href/click
        if (target.tagName === 'A' && target.getAttribute('href')) location.href = target.getAttribute('href');
        else target.click();
      });
      wrap.appendChild(clone);
    });
    (list || content).appendChild(wrap);
  }

  // ui.js toolbar_init(): the content header's .menu.toolbar is converted
  // into a ul.menu.toolbar.listing.iconized (items wrapped in li) so the
  // same element works inline on desktop and as a popup menu (via the
  // popupmenu class) on small screens, opened by an added kebab button.
  function toolbarInit() {
    var content = pane('layout-content');
    if (!content) return;
    var header = content.querySelector(':scope > .header');
    if (!header) return;
    var toolbar = header.querySelector(':scope > .menu.toolbar, :scope > .toolbar.menu');
    if (!toolbar || toolbar.tagName === 'UL') return;   // already converted
    var ul = document.createElement('ul');
    ul.className = 'menu toolbar listing iconized';
    ul.id = 'toolbar-menu';   // ui.js toolbar_init(): the source .menu.toolbar
    // is removed and the items re-hosted under this id
    Array.prototype.slice.call(toolbar.childNodes).forEach(function (ch) {
      if (ch.nodeType !== 1) return;  // drop whitespace text nodes (ui.js too)
      var li = document.createElement('li');
      li.setAttribute('role', 'menuitem');
      if (ch.classList.contains('spacer')) li.className = 'spacer';
      li.appendChild(ch);
      ul.appendChild(li);
    });
    toolbar.parentNode.replaceChild(ul, toolbar);
    ul.removeAttribute('role');  // the header div carries role=toolbar (ui.js keeps it)
    var kebab = header.querySelector('a.toolbar-menu-button');
    if (!kebab) {
      kebab = document.createElement('a');
      kebab.className = 'button icon toolbar-menu-button';
      kebab.href = '#menu';
      kebab.appendChild(document.createElement('span')).className = 'inner';
      header.appendChild(kebab);
    }
    kebab.setAttribute('data-popup', ul.id);
  }

  function resize() {
    computeScreenMode();
    applyLayout();
    screenResize();
  }
  document.addEventListener('DOMContentLoaded', resize);
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resize, 25);
  });

  // ui.js: buttons that should be hidden on small screen devices —
  // data-hidden="big|small|phone|large|lbs" becomes hidden-<mode> class
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-hidden]').forEach(function (el) {
      var v = el.getAttribute('data-hidden'); var re = /(large|big|small|phone|lbs)/g; var m;
        var parent = el.parentElement && el.parentElement.tagName === 'LI' ? el.parentElement : el;
      while ((m = re.exec(v))) parent.classList.add('hidden-' + m[1]);
    });
  });

  // ------------------------------------------------------ column navigation
  // ui.js layout_init(): header buttons drive pane visibility directly
  // (buttons.menu / back_sidebar / back_list / back_content click handlers).
  document.addEventListener('DOMContentLoaded', function () {
    // layout_init(): the initially selected pane is the "last selected" one
    last_selected = document.querySelector('#layout > div.selected') ||
      pane('layout-list') || pane('layout-sidebar') || pane('layout-content');
    if (last_selected) last_selected.classList.add('selected');

    document.querySelectorAll('a.task-menu-button').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); appMenu(true); });
    });
    document.querySelectorAll('a.back-sidebar-button').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); showSidebar(); });
    });
    document.querySelectorAll('a.back-list-button').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); showList(); });
    });
    document.querySelectorAll('a.back-content-button').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); showContent(); });
    });
    // close button in the menu drawer's popover-header
    var menu = pane('layout-menu');
    if (menu) {
      var x = menu.querySelector('.popover-header a.cancel');
      if (x) x.addEventListener('click', function (e) { e.preventDefault(); appMenu(false); });
    }

    initPopups();
    initList();
    initStandaloneMessage();
    initStack();
    initRefresh();
    initFabs();
    toolbarInit();
    // common_content_handler on frame load: a deep-linked message preview
    // makes the content pane the selected one on small screens
    var mframe = document.getElementById('messagecontframe');
    if (mframe && (window.innerWidth <= 768) &&
        (mframe.getAttribute('src') || '').indexOf('_uid=') >= 0) showContent();
    resize();
  });

  // ------------------------------------------------------------ dark mode
  document.addEventListener('DOMContentLoaded', function () {
    var t = document.getElementById('darktoggle');
    if (!t) return;
    function label() {
      var dark = document.documentElement.classList.contains('dark-mode');
      var inner = t.querySelector('.inner');
      if (inner) inner.textContent = dark ? 'Light mode' : 'Dark mode';
      // the class names the ACTION: sun (theme light) while dark is on,
      // moon (theme dark) while light is on — like the elastic ui.js
      t.classList.toggle('light', dark);
      t.classList.toggle('dark', !dark);
      t.setAttribute('title', dark ? 'Light mode' : 'Dark mode');
    }
    label();
    t.addEventListener('click', function (e) {
      e.preventDefault();
      var dark = document.documentElement.classList.toggle('dark-mode');
      document.cookie = 'colorMode=' + (dark ? 'dark' : 'light') + ';path=/;max-age=31536000';
      // ui.js switch_iframe_color_mode(): push the mode into same-origin
      // iframes (watermark, framed previews) that already rendered
      document.querySelectorAll('iframe').forEach(function (f) {
        try {
          var h = f.contentDocument && f.contentDocument.documentElement;
          if (h) h.classList.toggle('dark-mode', dark);
        } catch (err) { /* cross-origin: ignore like the reference */ }
      });
      label();
    });
  });

  // ------------------------------------------------------------ popup menus
  function initPopups() {
    var open = null; var drawer = null;
    // ui.js is_mobile(): phone and small widths render popups as a
    // right-side .popover drawer with a Close/Back header + overlay.
    function isMobile() { return mode === 'phone' || mode === 'small'; }
    function close() {
      if (drawer) {
        // restore the menu into its original position
        if (open._ccHome) open._ccHome.insertBefore(open, open._ccNext || null);
        if (drawer.wrap.parentNode) drawer.wrap.remove();
        if (drawer.overlay && drawer.overlay.parentNode) drawer.overlay.remove();
        drawer = null;
      }
      if (open) {
        open.classList.remove('open');
        if (open.classList.contains('searchoptions')) open.classList.add('hidden');
        open.style.position = ''; open.style.top = ''; open.style.left = '';
        open.style.maxHeight = '';
        if (open._ccTrig) open._ccTrig.setAttribute('aria-expanded', 'false');
        open._ccTrig = null;
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
        open._ccTrig = trig;
        if (!trig.hasAttribute('aria-haspopup')) {
          // ui.js:2327 -- popover triggers carry the menu a11y state
          trig.setAttribute('aria-haspopup', 'true');
          trig.setAttribute('aria-expanded', 'false');
        }
        menu.classList.remove('hidden');
        menu.classList.add('open');
        // inline panels (search options) expand in place; menus float
        if (menu.classList.contains('searchoptions')) {
          // stays inline below the searchbar
        } else if (isMobile()) {
          // bootstrap popover on mobile: full-height drawer from the right
          var wrap = document.createElement('div');
          wrap.className = 'popover';
          var hdr = document.createElement('div');
          hdr.className = 'popover-header';
          var back = document.createElement('a');
          back.className = 'button icon cancel';
          back.textContent = 'Close';
          back.addEventListener('click', function (ev) { ev.preventDefault(); close(); });
          hdr.appendChild(back);
          var body = document.createElement('div');
          body.className = 'popover-body scroller';
          open._ccHome = menu.parentNode;
          open._ccNext = menu.nextSibling;
          body.appendChild(menu);
          wrap.appendChild(hdr);
          wrap.appendChild(body);
          var ov = document.createElement('div');
          ov.className = 'popover-overlay';
          ov.style.left = '0';
          ov.style.right = '0';
          ov.addEventListener('click', close);
          document.body.appendChild(ov);
          document.body.appendChild(wrap);
          drawer = { wrap: wrap, overlay: ov };
        } else {
          // bootstrap popover on desktop (ui.js popup_init -> .popover()):
          // the menu moves into a .popover shell (arrow + popover-body) that
          // carries the border/shadow/font-size, positioned below the
          // trigger and flipped above when there is no room.
          var wrap = document.createElement('div');
          wrap.className = 'popover bs-popover-bottom bs-popover-auto show';
          wrap.setAttribute('role', 'tooltip');
          var arrow = document.createElement('div');
          arrow.className = 'arrow';
          var body = document.createElement('div');
          body.className = 'popover-body webkit-scroller';
          open._ccHome = menu.parentNode;
          open._ccNext = menu.nextSibling;
          body.appendChild(menu);
          wrap.appendChild(arrow);
          wrap.appendChild(body);
          document.body.appendChild(wrap);
          drawer = { wrap: wrap, overlay: null };
          // ui.js: cap the popup height below the window height
          menu.style.maxHeight = Math.min(36 * 15 - 1, window.innerHeight - 30) + 'px';
          var r = trig.getBoundingClientRect();
          var mw = wrap.offsetWidth;
          var mh = wrap.offsetHeight;
          var left = Math.max(4, Math.min(r.left + r.width / 2 - mw / 2,
                                          window.innerWidth - mw - 4));
          var top = r.bottom + 8;
          if (top + mh > window.innerHeight - 4 && r.top - mh - 8 > 4) {
            top = r.top - mh - 8;   // popover flip: place above
            wrap.classList.remove('bs-popover-bottom');
            wrap.classList.add('bs-popover-top');
          }
          wrap.style.left = (left + window.scrollX) + 'px';
          wrap.style.top = (top + window.scrollY) + 'px';
          arrow.style.left = Math.max(8, Math.min(r.left + r.width / 2 - left - 4, mw - 16)) + 'px';
        }
        trig.setAttribute('aria-expanded', 'true');
        menu.setAttribute('aria-hidden', 'false');
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
      var btnpane = document.createElement('div');
      btnpane.className = 'ui-dialog-buttonpane ui-widget-content ui-helper-clearfix';
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
      btnpane.appendChild(set);
      dlg.appendChild(btnpane);
    }

    // resizable grip (jQuery-UI resizable markup; Elastic themes .ui-icon.ui-resizable-se)
    var grip = document.createElement('span');
    grip.className = 'ui-resizable-handle ui-resizable-se ui-icon ui-icon-gripsmall-diagonal-se';
    grip.style.cssText = 'position:absolute;cursor:se-resize;width:12px;height:12px;right:1px;bottom:1px;z-index:2';
    dlg.appendChild(grip);
    grip.addEventListener('mousedown', function (e) {
      e.preventDefault();
      var h0 = dlg.offsetHeight; var y0 = e.clientY;
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
      var x0 = e.clientX; var y0 = e.clientY; var l0 = dlg.offsetLeft; var t0 = dlg.offsetTop;
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
    // Elastic renders every toolbar/menu button with role=button,
    // tabindex=0 and aria-disabled (html::button); mirror that once at init
    // so enabled() can maintain active/aria-disabled like rcmail.enable_command.
    document.querySelectorAll(
        '#mailtoolbar a[href], #replyall-menu li > a, #forward-menu li > a, ' +
        '#message-menu li > a, #download-menu li > a').forEach(function (a) {
      if (a.hasAttribute('role')) return;
      a.setAttribute('role', 'button');
      a.setAttribute('tabindex', '0');
      a.setAttribute('aria-disabled', a.classList.contains('disabled') ? 'true' : 'false');
    });
    function enabled(sel, on) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.classList.toggle('disabled', !on);
        // reference buttons carry 'active' + aria-disabled once the command
        // state is known (rcube_html::add_class in enable_command)
        if (el.classList.contains('active') || el.hasAttribute('role')) {
          el.classList.toggle('active', on);
          el.setAttribute('aria-disabled', on ? 'false' : 'true');
        }
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
      // 'reply-list' is only enabled when the message carries a List-Post
      // header (app.js:448 enable_command('reply-list', env.list_post))
      var mlRow = ctx.length === 1 ? list.querySelector('tr.message[data-uid="' + ctx[0] + '"]') : null;
      var isList = !!(mlRow && mlRow.getAttribute('data-ml') === '1');
      enabled('#replyall-menu a[data-mode="replylist"]', ctx.length === 1 && isList);
      enabled('#message-menu a', hasSel);
      enabled('#download-menu a', hasSel);
      if (ctx.length === 1) {
        var uid = ctx[0];
        var q = '_mbox=' + encodeURIComponent(boxOf(uid)) + '&_uid=' + uid;
        // reply/forward/edit links point at /compose?_mode=...; append context
        document.querySelectorAll(
            '#toolbar-menu a[href*="compose"], #forward-menu a[data-mode], ' +
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
          if (base === '#') extwin.setAttribute('href', '/message?' + q + '&_extwin=1');
        }
      }
    }

    // selection column toggle (stock: rcmail.enable_selection)
    var toggle = document.getElementById('list-toggle-button');
    if (toggle) {
      toggle.addEventListener('click', function (e) {
        e.preventDefault();
        var on = list.classList.toggle('selection');
        document.querySelectorAll('#listselect-menu a[data-select]').forEach(function (el) {
          el.classList.toggle('disabled', !on);
        });
        if (!on) {
          rows().forEach(function (r) {
            var cb = r.querySelector('td.selection input');
            if (cb) cb.checked = false;
          });
        }
        updateToolbar();
        window.cc_close_popups();
      });
    }

    // select-menu actions
    document.querySelectorAll('#listselect-menu a[data-select]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var selmode = a.getAttribute('data-select');
        rows().forEach(function (r) {
          var cb = r.querySelector('td.selection input');
          if (!cb) return;
          if (selmode === 'all' || selmode === 'page') cb.checked = true;
          else if (selmode === 'unread') cb.checked = r.classList.contains('unread');
          else if (selmode === 'flagged') cb.checked = r.classList.contains('flagged');
          else if (selmode === 'invert') cb.checked = !cb.checked;
          else if (selmode === 'none') cb.checked = false;
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
      var tr = e.target.closest('tr.message');
      if (!tr) return;
      // selection mode (reference rowselection): a row click toggles the
      // checkbox; the subject link still navigates/previews
      if (list.classList.contains('selection') && !e.target.closest('td.subject span.subject a')) {
        var cb2 = tr.querySelector('td.selection input');
        if (cb2) { cb2.checked = !cb2.checked; updateToolbar(); }
        return;
      }
      // Elastic: clicking anywhere in a message row focuses it and opens
      // the preview (only the anchor is a real href for keyboard/no-JS)
      var url = null;
      var a2 = e.target.closest('td.subject span.subject a');
      if (a2) url = a2.getAttribute('href');
      else {
        var link = tr.querySelector('td.subject span.subject a');
        if (link) url = link.getAttribute('href');
      }
      var frame = document.getElementById('messagecontframe');
      // Elastic opens the preview everywhere the layout is not single-pane
      // (is_mobile() = phone/small, <=768); normal/large keep list+content
      if (url && frame && window.innerWidth > 768) {
        e.preventDefault();
        frame.src = url + (url.indexOf('?') > -1 ? '&' : '?') + '_framed=1';
        var content = document.getElementById('layout-content');
        if (content) content.classList.add('selected');
        rows().forEach(function (r) { r.classList.remove('selected'); });
        tr.classList.add('selected');
        var icon = tr.querySelector('.msgicon.status');
        if (icon) { icon.classList.remove('unread'); icon.title = ''; }
        tr.classList.remove('unread');
        updateToolbar();
        setTimeout(scheduleRead, 300);
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
        if (names.length === 1) {
          field('_mbox_override', names[0]);
        } else if (names.length > 1) {
          field('_box_map', uids.map(function (u) { return u + ':' + boxOf(u); }).join(','));
        }
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
    function setThreadState(thmode) {
      var roots = rows().filter(function (r) { return r.getAttribute('data-depth') === '0'; });
      roots.forEach(function (root) {
        var hide = false;
        var sib = root.nextElementSibling;
        while (sib && sib.getAttribute('data-depth') !== null && sib.getAttribute('data-depth') !== '0') {
          if (thmode === 'all') sib.style.display = '';
          else if (thmode === 'none') sib.style.display = 'none';
          else if (thmode === 'unread') {
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
      var folder = frame.getAttribute('data-folder');
      clearTimeout(scheduleRead._t);
      scheduleRead._t = setTimeout(function () {
        var fd = new FormData();
        fd.append('_mbox', folder); fd.append('_act', 'read'); fd.append('_uids[]', uid);
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

  // Standalone message pages (extwin/print) have no list: the toolbar acts
  // on the uid the server rendered into #mailtoolbar's data attrs. Commands
  // post to /mail/act like the list does, then land on the shell.
  function initStandaloneMessage() {
    var tb = document.getElementById('mailtoolbar');
    if (!tb || document.getElementById('messagelist')) return;   // shell handles itself
    var uid = tb.getAttribute('data-uid'); var box = tb.getAttribute('data-box');
    if (!uid) return;
    document.body.classList.add('has-selection');

    function post(fields) {
      var f = document.createElement('form');
      f.method = 'post'; f.action = '/mail/act'; f.style.display = 'none';
      Object.keys(fields).forEach(function (k) {
        var i = document.createElement('input');
        i.type = 'hidden'; i.name = k; i.value = fields[k];
        f.appendChild(i);
      });
      document.body.appendChild(f); f.submit();
    }
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-act], #message-menu a[data-mode]');
      if (!a || a.classList.contains('disabled')) return;
      var cmd = a.getAttribute('data-act') || a.getAttribute('data-mode');
      e.preventDefault();
      if (cmd === 'delete') {
        if (confirm('Really delete the message?')) {
          post({ _mbox: box, _uids: uid, _act: 'delete' });
        }
      } else if (cmd === 'archive' || cmd === 'read' || cmd === 'unread' ||
                 cmd === 'flag' || cmd === 'unflag' ||
                 cmd === 'move' || cmd === 'copy') {
        post({ _mbox: box, _uids: uid, _act: cmd,
               _dest: a.getAttribute('data-dest') || '' });
      } else if (cmd === 'edit') {
        location.href = '/compose?_mode=edit&_mbox=' +
          encodeURIComponent(box) + '&_uid=' + uid;
      }
    });
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
      var out = []; var depth = 0; var cur = '';
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
      if (table) {
        table.querySelectorAll('.selected').forEach(function (el) {
          el.classList.remove('selected', 'focused');
          el.setAttribute('aria-selected', 'false');
        });
      }
      row.classList.add('selected', 'focused');
      row.setAttribute('aria-selected', 'true');
      frame.src = row.getAttribute('data-framed-href');
      // common_content_handler: on small screens showing the content frame
      // makes it the selected pane (replaces the list)
      if (mode === 'phone' || mode === 'small') showContent();
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

  // ---------------------------------------------------------------- open_window
  // app.js:2259 — sized popup window unless the 'standard_windows' pref
  // asks for regular browser windows (which can then be handled as tabs).
  var standard_windows = document.body.getAttribute('data-standard-windows') === '1';
  window.cc_open_window = function (url, small) {
    url += (url.indexOf('?') > -1 ? '&' : '?') + '_extwin=1';
    var features = '';
    if (!standard_windows) {
      var w = Math.min(small ? 900 : 1150, window.innerWidth);
      var h = window.innerHeight;
      var l = (window.screenLeft || window.screenX) + 20;
      var t = (window.screenTop || window.screenY) + 20;
      features = 'width=' + w + ',height=' + h + ',top=' + t + ',left=' + l +
        ',resizable=yes,location=no,scrollbars=yes,toolbar=no,menubar=no,status=no';
    }
    var win = window.open(url, 'rcmextwin' + Date.now(), features);
    // popup-blocker detection like app.js:2281
    if (!win || win.closed) {
      if (window.cc_simple_dialog) cc_simple_dialog('The popup window was blocked!', 'Error');
      return null;
    }
    return win;
  };

  // compose_extwin / message_extwin (app.js:4855 open_compose_step,
  // app.js:2755 show_message): the same actions open popups instead of
  // navigating — except while already inside an extwin popup.
  var in_extwin = /[?&]_extwin=1/.test(location.search);
  if (!in_extwin && document.body.getAttribute('data-compose-extwin') === '1') {
    document.addEventListener('click', function (e) {
      var a = e.target.closest('a[href]');
      if (!a || a.getAttribute('data-act') || a.target === '_blank') return;
      var href = a.getAttribute('href');
      if (href.indexOf('/compose') !== 0) return;
      e.preventDefault();
      window.cc_open_window(href, false);
    }, true);
  }
  if (!in_extwin && document.body.getAttribute('data-message-extwin') === '1') {
    document.addEventListener('click', function (e) {
      var a = e.target.closest('td.subject a[href^="/message"], a.extwin[href^="/message"]');
      if (!a) return;
      // preview mode is unaffected (show_message preview=true, app.js:2740);
      // only the standalone open becomes a small popup window
      if (window.innerWidth > 768 && document.getElementById('messagecontframe')) return;
      e.preventDefault();
      window.cc_open_window(a.getAttribute('href'), true);
    }, true);
  }

  // ------------------------------------------------------------ auto refresh
  function initRefresh() {
    var mins = parseInt(document.body.getAttribute('data-refresh-interval') || '0', 10);
    if (!mins || !document.getElementById('messagelist')) return;
    function tick() {
      var url = new URL(location.href);
      // Elastic's check_mime_message reloads the list *with* the previewed
      // message (_uid stays in the request), so the content frame and the
      // focused row survive the refresh. Dropping _uid here made the opened
      // message vanish and its row lose focus after one interval.
      var sel = document.querySelector('#messagelist tr.selected, #messagelist tr.focused');
      var uid = sel && sel.getAttribute('data-uid');
      if (uid) url.searchParams.set('_uid', uid);
      else url.searchParams.delete('_uid');
      location.href = url.toString();
    }
    setTimeout(tick, mins * 60000);
    window.cc_refresh_tick = tick; // exposed for tests
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
