/* CraftCube UI — replicates the essential elastic-skin behaviors:
   layout size classes, column navigation (#menu/#sidebar/#back),
   dark-mode toggle, message-list selection + toolbar enabling,
   popup menus, framed message preview. IDs/classes match what
   mail.html / message_part.html actually render. */
(function () {
  'use strict';

  // rcube app.get_label() (app.js): catalogue text with $var substitution
  function cc_get_label(key, vars) {
    var text = (window.cc_labels || {})[key] || ('[' + key + ']');
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        text = text.replace('$' + k, vars[k]);
      });
    }
    return text.replace(/\\n/g, '\n');
  }
  window.cc_get_label = cc_get_label;

  // Settings > Folders: the subscription switch posts the same thing the
  // reference's folder_subscribe/folder_unsubscribe AJAX actions do.
  window.cc_subscription_toggle = function (folder, subscribed) {
    var f = document.createElement('form');
    f.method = 'post';
    f.action = '/settings/folders';
    f.style.display = 'none';
    [['_act', subscribed ? 'subscribe' : 'unsubscribe'],
     ['folder', folder]].forEach(function (p) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = p[0]; i.value = p[1];
      f.appendChild(i);
    });
    document.body.appendChild(f);
    f.submit();
  };

  // Reference: rcube_webmail.set_unread_count()/set_unread_count_display()
  // (program/js/app.js:8976): the INBOX unread count drives the document
  // title ("(n) ...", app.js:9039) and reading a message decrements its
  // folder badge client-side (app.js:2787) without a page reload.
  function folderLi(mbox) {
    return document.querySelector('#mailboxlist li[data-name="' + mbox + '"]');
  }
  function setPageTitleUnread(count) {
    var reg = /^\([0-9]+\)\s+/i;
    var t = String(document.title);
    document.title = count ? '(' + count + ') ' + t.replace(reg, '')
                           : t.replace(reg, '');
  }
  function setUnreadCount(mbox, count, setTitle) {
    var li = folderLi(mbox);
    if (!li) return;
    var span = li.querySelector('span.unreadcount');
    if (count > 0) {
      if (!span) {
        span = document.createElement('span');
        span.className = 'unreadcount skip-content';
        li.appendChild(span);
      }
      span.textContent = count;
    } else if (span) {
      span.remove();
    }
    li.classList.toggle('unread', count > 0);
    if (setTitle) setPageTitleUnread(count);
  }
  function unreadDecrementOnRead(row, folder) {
    // app.js:2787 — only INBOX updates the title, and never in a
    // multifolder (search across folders) listing
    if (!row.classList.contains('unread') || !folder) return;
    if (document.querySelector('#messagelist .folder-name')) return;
    var li = folderLi(folder);
    var span = li && li.querySelector('span.unreadcount');
    var n = span ? parseInt(span.textContent, 10) || 0 : 0;
    setUnreadCount(folder, n > 1 ? n - 1 : 0, folder === 'INBOX');
  }

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
    // reference window_width(): framed pages measure the TOP window, so an
    // iframe inside a wide shell keeps the parent's layout mode (elastic ui.js)
    var w;
    try {
      var wn = window;
      while (wn !== wn.top && wn.parent && wn.parent.document) wn = wn.parent;
      w = wn.innerWidth;
    } catch (e) { w = window.innerWidth; }
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
      var lblD = t.getAttribute('data-label-dark') || 'Dark mode';
      var lblL = t.getAttribute('data-label-light') || 'Light mode';
      if (inner) inner.textContent = dark ? lblL : lblD;
      // the class names the ACTION: sun (theme light) while dark is on,
      // moon (theme dark) while light is on — like the elastic ui.js
      t.classList.toggle('light', dark);
      t.classList.toggle('dark', !dark);
      t.setAttribute('title', dark ? lblL : lblD);
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
    // app.js simple_dialog: a string message is wrapped in a content div;
    // spacing comes from the dialog content box padding (1em/1em/.5em)
    if (typeof content === 'string') {
      var txt = document.createElement('div');
      txt.className = 'cc-dialog-text';
      txt.textContent = content;
      content = txt;
    }
    var isIframe = content.tagName === 'IFRAME';
    var popup = document.createElement('div');
    // jQuery-UI puts the dialog content inside .popup.ui-dialog-content
    // .ui-widget-content; the skin styles (padding, >.popupmenu display
    // override, .iframe reset) key off those classes
    popup.className = 'popup ui-dialog-content ui-widget-content'
      + (isIframe ? ' iframe' : '');
    popup.appendChild(content);
    if (!isIframe) {
      // elastic bootstrap_style() for a dialog context: consistent control
      // classes on the (possibly cloned) form fields
      var supported = 'input:not(.button,.no-bs,[type=button],[type=radio],[type=checkbox],[type=file]),textarea';
      popup.querySelectorAll(supported).forEach(function (el) { el.classList.add('form-control'); });
      popup.querySelectorAll('[type=checkbox]').forEach(function (el) { el.classList.add('form-check-input'); });
      popup.querySelectorAll('select').forEach(function (el) { el.classList.add('form-control', 'custom-select'); });
    }

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
    if (isIframe) {
      popup.style.height = h + 'px';
    } else if (opts.height) {
      // opts.height pins the reference's measured content-box height (the
      // cloned .popupmenu needs a definite parent box for height:100%)
      popup.style.flex = '0 0 auto';
      popup.style.height = Math.min(opts.height, window.innerHeight - 40 - chrome) + 'px';
    } else {
      // simple_dialog()/confirm_dialog() pass noresize: the content box
      // takes its natural height (reference confirm popup measures 42px)
      popup.style.flex = '0 0 auto';
    }
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

  // ------------------------------------------------- confirm_dialog (app.js:8796)
  // confirm_dialog(content, button_label, action): simple_dialog with title
  // 'confirmationtitle' ("Are you sure..."), the action button carrying the
  // command class (elastic styles .delete as btn-danger) and a Cancel
  // button. Reference measurement: 502x158, message sits directly in .popup.
  window.cc_confirm_dialog = function (message, button_label, action_fn) {
    var label = button_label || 'delete';
    var dlg = ccDialog(message, cc_get_label('confirmationtitle'), {
      width: 500, // reference show_popup_dialog default (dialog 502 incl. border)
      buttons: [
        { label: cc_get_label(label), cls: 'mainaction ' + label + ' btn-danger',
          click: function () { dlg.close(); action_fn(); } },
        { label: cc_get_label('cancel'), cls: 'cancel',
          click: function () { dlg.close(); } },
      ],
    });
    return dlg;
  };

  // ------------------------------------------------- mdn_request_dialog (app.js:4630)
  // "Send read receipt?" dialog: Send / Ignore and, when the pref asks to
  // remember (mdn_request_save 3/5), "Always send to <email>". Closing the
  // dialog marks the message $MDNSent unless Send took over the action.
  window.cc_mdn_dialog = function (uid, mbox, save, sender) {
    var props = { _uid: uid, _mbox: mbox };
    var action = 'mdnsent';          // dialog close marks the message
    function closeAndPost() {
      var fd = new FormData();
      if (action === 'sendmdn') {
        fd.append('_uid', props._uid); fd.append('_mbox', props._mbox);
        if (props._save) { fd.append('_save', props._save); fd.append('_address', props._address || ''); }
        fetch('/mail/sendmdn', { method: 'POST', body: fd })
          .then(function () {
            // the receiptsent flash renders in the app shell's stack
            (window.top !== window.self ? parent : window).location.reload();
          });
      } else {
        fd.append('_mbox', mbox); fd.append('_act', 'mdnsent'); fd.append('_uids[]', uid);
        fetch('/mail/act', { method: 'POST', body: fd });
      }
    }
    var buttons = [{
      label: cc_get_label('send'), cls: 'mainaction send',
      click: function () { action = 'sendmdn'; dlg.close(); },
    }, {
      label: cc_get_label('ignore'), cls: 'cancel',
      click: function () { dlg.close(); },
    }];
    if (save) {
      buttons.unshift({
        label: cc_get_label('sendalwaysto', { email: sender.mailto || '' }), cls: 'mainaction send',
        click: function () {
          props._save = save; props._address = sender.string || sender.mailto;
          action = 'sendmdn'; dlg.close();
        },
      });
    }
    var body = document.createElement('div');
    body.textContent = cc_get_label('mdnrequest');
    var dlg = ccDialog(body, cc_get_label('sendreceipt'), {
      height: 200, buttons: buttons, onclose: closeAndPost,
    });
    return dlg;
  };
  window.cc_iframe_dialog = function (src, title, height, opts) {
    opts = opts || {};
    var f = document.createElement('iframe');
    f.src = src;
    f.style.cssText = 'width:100%;height:100%;border:0';
    var d = ccDialog(f, title, { height: height || 400,
                                 width: opts.width || 604,
                                 buttons: opts.buttons,
                                 buttons_previous: opts.buttons_previous,
                                 onclose: opts.onclose });
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
    // title badge on load, like the reference's initial set_unread_count()
    var inboxLi = folderLi('INBOX');
    if (inboxLi) {
      var inboxCount = inboxLi.querySelector('span.unreadcount');
      setPageTitleUnread(inboxCount ? parseInt(inboxCount.textContent, 10) || 0 : 0);
    }
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
        '#message-menu li > a, #zipdownload-menu li > a, ' +
        '#markmessage-menu li > a, #mailboxoptions-menu li > a, ' +
        '#listselect-menu li > a, #threadselect-menu li > a, #list-menu li > a'
    ).forEach(function (a) {
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
          el.setAttribute('tabindex', on ? '0' : '-1');
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
      // 'import' is a folder-level command (mail_get.php import), not a
      // per-message action: it must stay enabled without a selection
      enabled('#message-menu a:not(.import)', hasSel);
      enabled('#message-menu a.import', true);
      enabled('#zipdownload-menu a', hasSel);
      // ui.js also enables the Mark submenu items with a selection
      enabled('#markmessage-menu a', hasSel);
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
        ['#tb-print', '#rcmbtn132', '#tb-source'].forEach(function (idSel) {
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
          rows().forEach(function (r) { markRow(r, false); });
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
          if (selmode === 'all' || selmode === 'page') markRow(r, true);
          else if (selmode === 'unread') markRow(r, r.classList.contains('unread'));
          else if (selmode === 'flagged') markRow(r, r.classList.contains('flagged'));
          else if (selmode === 'invert') markRow(r, !r.classList.contains('selected'));
          else if (selmode === 'none') markRow(r, false);
        });
        updateToolbar();
        window.cc_close_popups();
      });
    });

    // ---- row selection: port of rcube_list_widget::select_row (list.js).
    // Plain click replaces the selection, ctrl toggles, shift extends from
    // the anchor. Selection state lives on tr.selected with the checkbox
    // kept in sync. Rows never open on single click: elastic registers the
    // subject link with mouse_activation 'keyboard_only', so the mouse
    // selects (dblclick opens) and the href only fires on keyboard
    // activation (click events with detail === 0).
    var selAnchor = null;
    function rowLink(tr) {
      return tr.querySelector('td.subject span.subject a');
    }
    function markRow(tr, on) {
      tr.classList.toggle('selected', !!on);
      tr.setAttribute('aria-selected', on ? 'true' : 'false');
      var cb = tr.querySelector('td.selection input');
      if (cb) cb.checked = !!on;
    }
    function clearSel() { rows().forEach(function (r) { markRow(r, false); }); }
    function focusRow(tr) {
      rows().forEach(function (r) { r.classList.remove('focused'); });
      tr.classList.add('focused');
    }
    function selectRow(tr, ctrl, shift) {
      var all = rows();
      if (shift && selAnchor && all.indexOf(selAnchor) >= 0) {
        var a = all.indexOf(selAnchor), b = all.indexOf(tr);
        if (!ctrl) clearSel();
        for (var i = Math.min(a, b); i <= Math.max(a, b); i++) markRow(all[i], true);
      } else if (ctrl) {
        markRow(tr, !tr.classList.contains('selected'));
        selAnchor = tr;
      } else {
        clearSel();
        markRow(tr, true);
        selAnchor = tr;
      }
      focusRow(tr);
      updateToolbar();
    }

    // interactions: flag toggle / selection
    list.addEventListener('change', function (e) {
      if (e.target.type !== 'checkbox') return;
      var tr = e.target.closest('tr.message');
      if (tr) {
        // list.js checkbox onchange: select_row(uid, key||CONTROL_KEY) --
        // the checkbox already flipped natively, mirror it onto the row
        markRow(tr, e.target.checked);
        if (e.target.checked) { selAnchor = tr; focusRow(tr); }
      } else {
        // header 'select' checkbox toggles every row on the page
        rows().forEach(function (r) { markRow(r, e.target.checked); });
      }
      updateToolbar();
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
      // the checkbox is always its own business (rowselection ignores
      // input targets; the native toggle must not be undone here)
      if (e.target.tagName === 'INPUT') { updateToolbar(); return; }
      var a2 = e.target.closest('a');
      if (window.innerWidth <= 768) {
        // mobile (elastic phone/small layouts): tap anywhere opens the row
        if (!a2) {
          var ml = rowLink(tr);
          if (ml) {
            e.preventDefault();
            window.location.href = ml.getAttribute('href');
            return;
          }
        }
        selAnchor = tr; focusRow(tr); updateToolbar();
        return;
      }
      if (a2) {
        if (e.detail !== 0) e.preventDefault();
        else { selAnchor = tr; focusRow(tr); updateToolbar(); return; }
      }
      selectRow(tr, e.ctrlKey || e.metaKey, e.shiftKey);
      previewRow(tr, e.ctrlKey || e.metaKey || e.shiftKey);
    });
    // reference widescreen behavior: a plain click (and keyboard focus
    // moves) previews the message in the third column through the framed
    // view (show_message(..., 'preview')); dblclick/Enter still opens the
    // full reader page. Multi-selection does not preview (rcmail shows a
    // preview only for a single-message selection).
    function previewRow(tr, multi) {
      if (multi || window.innerWidth <= 768) return;
      var frame = document.getElementById('messagecontframe');
      if (!frame || !tr) return;
      var uid = tr.getAttribute('data-uid');
      if (!uid) return;
      var url = '/message?_mbox=' +
        encodeURIComponent(tr.getAttribute('data-box') || mbox) +
        '&_uid=' + uid + '&_framed=1';
      // -1/deferred read marking stays with the preview frame (views
      // renders data-read-time; server passes _noseen so the raw \Seen
      // flag is not touched before the timer fires)
      if ((frame.getAttribute('data-read-time') || '0') !== '0') url += '&_noseen=1';
      frame.src = url;
    }
    // list.js dblclick: open the double-clicked message (full page view,
    // same as the reference top-level navigation to _action=view)
    list.addEventListener('dblclick', function (e) {
      var tr = e.target.closest('tr.message');
      if (!tr) return;
      var a = rowLink(tr);
      if (a) window.location.href = a.getAttribute('href');
    });
    // ------------------------------------------------------------ drag&drop
    // reference drag_start/show_dragmenu/drag_menu_action: dragging selected
    // rows onto a sidebar folder opens the Move/Copy menu at the drop point
    var dragUids = null;
    var dragMenu = document.getElementById('dragmessage-menu');
    var dropHl = null;
    function clearDropHl() { if (dropHl) dropHl.classList.remove('droptarget'); dropHl = null; }
    function hideDragMenu() {
      if (!dragMenu) return;
      dragMenu.classList.remove('open');
      dragMenu.style.display = ''; dragMenu.style.top = ''; dragMenu.style.left = '';
    }
    rows().forEach(function (r) { r.draggable = true; });
    list.addEventListener('dragstart', function (e) {
      var tr = e.target.closest('tr.message');
      if (!tr) return;
      if (!tr.classList.contains('selected')) selectRow(tr, false, false);
      dragUids = toolbarContext();
      e.dataTransfer.setData('text/plain', 'messages');
      e.dataTransfer.effectAllowed = 'copyMove';
    });
    list.addEventListener('dragend', clearDropHl);
    document.querySelectorAll('#mailboxlist li[data-name]').forEach(function (li) {
      var name = li.getAttribute('data-name');
      li.addEventListener('dragover', function (e) {
        if (!dragUids || name === mbox) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (dropHl !== li) { clearDropHl(); li.classList.add('droptarget'); dropHl = li; }
      });
      li.addEventListener('dragleave', function () {
        if (dropHl === li) li.classList.remove('droptarget');
      });
      li.addEventListener('drop', function (e) {
        e.preventDefault();
        clearDropHl();
        if (!dragUids || !dragMenu || name === mbox) return;
        // app.js drag_end: SHIFT+drop shows the Move/Copy menu; a plain drop
        // executes move immediately (drag_menu returns true only for SHIFT).
        if (e.shiftKey) {
          dragMenu._dest = name;
          dragMenu.classList.add('open');
          dragMenu.style.position = 'fixed';
          dragMenu.style.display = 'block';
          dragMenu.style.top = Math.max(4, e.clientY - 12) + 'px';
          dragMenu.style.left = Math.max(4, e.clientX - 12) + 'px';
        } else {
          act('move', dragUids, { _dest: name });
        }
        dragUids = null;
      });
    });
    if (dragMenu) {
      dragMenu.querySelectorAll('a[data-dragact]').forEach(function (a) {
        a.addEventListener('click', function (e) {
          e.preventDefault();
          var dest = dragMenu._dest, uids = dragUids;
          hideDragMenu();
          if (!dest || !uids || !uids.length) return;
          act(a.getAttribute('data-dragact'), uids, { _dest: dest });
        });
      });
      document.addEventListener('mousedown', function (e) {
        if (dragMenu.classList.contains('open') &&
            !e.target.closest('#dragmessage-menu')) hideDragMenu();
      });
    }
    // keyboard row navigation (rcube_list_widget::keyup_select, arrows)
    document.addEventListener('keydown', function (e) {
      var cur = list.querySelector('tr.message.focused');
      if (!cur) return;
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' ||
                t.tagName === 'SELECT' || t.isContentEditable)) return;
      var all = rows(), i = all.indexOf(cur), n = -1;
      if (e.key === 'ArrowDown') n = Math.min(i + 1, all.length - 1);
      else if (e.key === 'ArrowUp') n = Math.max(i - 1, 0);
      else return;
      e.preventDefault();
      if (n >= 0 && all[n] !== cur) {
        selectRow(all[n], e.ctrlKey || e.metaKey, e.shiftKey);
        previewRow(all[n], e.ctrlKey || e.metaKey || e.shiftKey);
        all[n].scrollIntoView(false);
      }
    });

    // toolbar/popup command links
    document.querySelectorAll('#mailtoolbar a[data-act], .popupmenu a[data-act]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var cmd = a.getAttribute('data-act');
        if (cmd === 'empty') {
          // purge_mailbox(): confirm_dialog(purgefolderconfirm, 'delete')
          cc_confirm_dialog(cc_get_label('purgefolderconfirm'), 'delete',
            function () { act('empty', [], {}); });
        } else if (cmd === 'markallread') {
          act('markallread', [], {});
        } else if (cmd === 'delete') {
          // delete_message(): with a trash defined this is a silent
          // move-to-trash; only shift+delete confirms (permanent). The
          // server decides trash vs permanent, so no confirmation here.
          var uids = toolbarContext();
          if (uids.length) {
            var extra = {};
            var sel = document.querySelector('#messagelist tr.selected');
            if (sel) extra._return_uid = sel.getAttribute('data-uid') || '';
            act('delete', uids, extra);
          }
        } else if (cmd === 'archive') {
          act('archive', toolbarContext(), {});
        } else {
          act(cmd, toolbarContext(), {});
        }
        window.cc_close_popups();
      });
    });

    // Move to... / Copy to... open the shared reference folder-selector.
    // The clicked toolbar item decides the action; the selector itself has
    // no action-specific classes or heading (app.js entity_selector).
    var folderSelector = document.getElementById('folder-selector');
    document.querySelectorAll('[data-folder-action]').forEach(function (a) {
      a.addEventListener('click', function () {
        if (folderSelector) folderSelector._action = a.getAttribute('data-folder-action');
      });
    });
    if (folderSelector) {
      folderSelector.querySelectorAll('a[data-dest]').forEach(function (a) {
        a.addEventListener('click', function (e) {
          e.preventDefault();
          if (a.classList.contains('virtual')) return;
          var dest = a.getAttribute('data-dest');
          if (!dest || dest === mbox) return;  // move_messages: current folder no-op
          var uids = toolbarContext();
          if (!uids.length) return;
          act(folderSelector._action || 'move', uids, { _dest: dest });
          window.cc_close_popups();
        });
      });
    }

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

    // list-options dialog applies sort/order/list-mode (ui.js
    // menu_messagelist save_func -> rcmail.set_list_options); reads the
    // dialog's cloned selects when a root is given, else the page menu
    window.cc_apply_list_options = function (root) {
      root = root || document.getElementById('listoptions-menu');
      if (!root) return;
      var sels = root.querySelectorAll('select');
      if (sels.length < 3) return;
      var col = sels[0].value;
      var ord = sels[1].value.toLowerCase();
      var mode = sels[2].value;
      var url = new URL(location.href);
      url.searchParams.set('_sort', col);
      url.searchParams.set('_sort_order', ord);
      url.searchParams.set('_mode', mode);
      url.searchParams.delete('_page');
      // reference set_list_options stores the state (env + folder view
      // mode); ask the server to persist it so paging/back/folders keep it
      url.searchParams.set('_save_opts', '1');
      location.href = url.toString();
    };

    // ui.js menu_messagelist(): the Options link opens a modal dialog with
    // a clone of #listoptions-menu (ids/labels suffixed -clone), applied on
    // Save; it is not an inline popup menu
    window.ccDialog = ccDialog;  // shared with cc_import_dialog (IIFE tail)
    window.cc_listoptions_dialog = function (elem, event) {
      if (event) event.preventDefault();
      var src = document.getElementById('listoptions-menu');
      if (!src) return false;
      var clone = src.cloneNode(true);
      clone.removeAttribute('id');
      clone.removeAttribute('style');
      // reference keeps the popupmenu classes (the skin has a
      // .ui-dialog-content>.popupmenu display override); only a stale
      // open/inactive state from the old inline popup must go
      clone.classList.remove('open', 'inactive');
      clone.querySelectorAll('select').forEach(function (s) {
        s.id = s.id + '-clone';
      });
      clone.querySelectorAll('label').forEach(function (l) {
        if (l.getAttribute('for')) l.setAttribute('for', l.getAttribute('for') + '-clone');
      });
      clone.querySelectorAll('select').forEach(function (s) {
        s.removeAttribute('onchange');
      });
      var dlg = ccDialog(clone, cc_get_label('listoptionstitle'), {
        width: 528,   // reference dialog measured 530 incl. border
        height: 198,  // reference popup content box measured 198 (dialog 314)
        buttons: [
          { label: cc_get_label('save'), cls: 'mainaction save',
            click: function () { cc_apply_list_options(clone); } },
          { label: cc_get_label('cancel'), cls: 'cancel',
            click: function () { dlg.close(); } },
        ],
      });
      return false;
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

    // Download... submenu (zipdownload): eml = single raw .eml download
    // (reference viewsource _save=1); mbox/maildir = plugin zip of selection
    document.querySelectorAll('#zipdownload-menu a[data-dlfmt]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        e.preventDefault();
        if (a.classList.contains('disabled')) return;
        var uids = toolbarContext();
        if (!uids.length) return;
        var fmt = a.getAttribute('data-dlfmt');
        var box = boxOf(uids[0]);
        var url;
        if (fmt === 'eml') {
          url = '/message?_mbox=' + encodeURIComponent(box) +
                '&_uid=' + encodeURIComponent(uids[0]) + '&_save=1';
        } else {
          url = '/message/export?_mode=' + fmt +
                '&_mbox=' + encodeURIComponent(box);
          uids.forEach(function (u) {
            var b = boxOf(u);
            url += '&_uid[]=' + encodeURIComponent(b === box ? u : u + '-' + b);
          });
        }
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
        if (a.classList.contains('disabled')) return;
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
      // only when a preview is actually showing (read_when_previewed);
      // a blank frame means the row is merely selected, never mark read
      if (!frame || !frame.src || frame.src === 'about:blank') return;
      // the watermark empty state means 'nothing previewed' (env:blankpage)
      if (frame.src.indexOf('watermark') >= 0) { clearTimeout(scheduleRead._t); return; }
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
        // delete_message(): silent move-to-trash (see toolbar handler); the
        // server decides trash vs permanent
        post({ _mbox: box, _uids: uid, _act: 'delete' });
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
        // always sync the posted value: the compose-restore dialog and the
        // extwin snapshot seed chips with seed=true and never rebuild after
        rebuild();
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

  // framed (iframe) pages: reference ui.js drops the task rail and sidebar
  // from every *_framed=1 page (they belong to the parent window only)
  if (document.documentElement.classList.contains('iframe')) {
    ['#layout-menu', '#layout-sidebar'].forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) el.remove();
    });
  }

  // ------------------------------- rows opening a section in a local frame
  // (ui.js: clicking a settings section row loads the form into
  //  #preferences-frame and marks the row selected, URL unchanged;
  //  toolbar buttons — Create — navigate the frame too)
  document.querySelectorAll('tr[data-framed-href], li[data-framed-href], a[data-framed-href]').forEach(cc_bind_framed_row);
  function cc_bind_framed_row(row) {
    if (row.hasAttribute('data-framed-bound')) return;
    row.setAttribute('data-framed-bound', '1');
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
      // cross-list deselection (elastic: sidebar and section list never
      // carry the selection at the same time)
      var other = row.tagName === 'LI'
        ? document.querySelector('#sections-table')
        : document.querySelector('#settings-menu');
      if (other) other.querySelectorAll('.selected').forEach(function (el) {
        el.classList.remove('selected', 'focused');
        el.setAttribute('aria-selected', 'false');
      });
      if (row.tagName !== 'A') {
        row.classList.add('selected', 'focused');
        row.setAttribute('aria-selected', 'true');
      }
      frame.src = row.getAttribute('data-framed-href');
      cc_record_select(row);
      // common_content_handler: on small screens showing the content frame
      // makes it the selected pane (replaces the list)
      if (mode === 'phone' || mode === 'small') showContent();
    }
    row.addEventListener('click', function (e) {
      if (row.tagName === 'A') { e.preventDefault(); go(); return; }
      if (e.target.closest('a, input, button')) return;
      go();
    });
    row.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') go();
    });
  }

  // app.js update_identity_row()/update_response_row(): after a framed
  // save the editor page syncs the parent list — insert+select on create,
  // cell text replace on update (reference replaces the identity cell with
  // the bare name, email included only on a full list render)
  window.cc_settings_row_upsert = function (o) {
    var list = document.querySelector(o.list);
    if (!list) return;
    var tbody = list.querySelector('tbody') || list;
    var sel = 'tr[data-record-id="' + o.id + '"]';
    var row = tbody.querySelector(sel);
    function select_only(tr) {
      tbody.querySelectorAll('tr.selected, tr.focused').forEach(function (el) {
        el.classList.remove('selected', 'focused');
        el.setAttribute('aria-selected', 'false');
      });
      tr.classList.add('selected', 'focused');
      tr.setAttribute('aria-selected', 'true');
    }
    if (row) {
      var cell = row.querySelector('td');
      if (cell) cell.textContent = o.name;
      if (o.add) select_only(row);
      return;
    }
    if (!o.add) return;
    var base = tbody.querySelector('tr[data-framed-href]');
    var tr;
    if (base) {
      tr = base.cloneNode(true);
    } else {
      tr = document.createElement('tr');
      tr.setAttribute('role', 'option');
      tr.setAttribute('tabindex', '0');
      var td = document.createElement('td');
      td.className = o.list.indexOf('responses') > -1 ? 'name' : 'mail';
      tr.appendChild(td);
    }
    tr.id = 'rcmrow' + o.id;
    tr.setAttribute('data-record-id', o.id);
    tr.setAttribute('aria-selected', 'false');
    tr.removeAttribute('onclick');
    var href = (o.list.indexOf('responses') > -1
      ? '/settings/response/edit/'
      : '/settings/identity/edit/') + o.id + '?_framed=1';
    tr.setAttribute('data-framed-href', href);
    tr.querySelector('td').textContent = o.name;
    // fresh row needs the framed-click behavior
    tbody.appendChild(tr);
    cc_bind_framed_row(tr);
    select_only(tr);
    var empty = list.parentNode.querySelector('.tablenoselrows, tr.a-empty');
    if (empty) empty.remove();
  };

  // elastic identities/responses lists: Delete is disabled until a record is
  // selected; selecting a row arms it for that record (rcmail.enable_command)
  function cc_record_select(row) {
    var del = document.querySelector('#layout-content .toolbar a.delete');
    if (!del || !del.hasAttribute('data-delete-base')) return;
    var rid = row.tagName !== 'A' ? row.getAttribute('data-record-id') : null;
    if (!rid) {
      del.classList.add('disabled');
      del.setAttribute('tabindex', '-1');
      del.setAttribute('aria-disabled', 'true');
      del.onclick = null;
      return;
    }
    del.classList.remove('disabled');
    del.removeAttribute('tabindex');
    del.setAttribute('aria-disabled', 'false');
    del.onclick = function (e) {
      e.preventDefault();
      // RC settings deletes go through confirm_dialog() (styled
      // 'Are you sure...' dialog), never the native window.confirm
      cc_confirm_dialog(
        del.getAttribute('data-confirm') || 'Delete?',
        'delete',
        function () {
          var f = document.createElement('form');
          f.method = 'post';
          f.action = del.getAttribute('data-delete-base') + '/' + rid + '/delete';
          document.body.appendChild(f);
          f.submit();
        });
      return false;
    };
  }

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
      if (window.cc_simple_dialog) cc_simple_dialog(cc_get_label('windowopenerror'), 'Error');
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
  // app.js add_callback('check-recent') loop: poll the check_recent XHR and
  // apply its set_unread_count commands; reload the page only when the
  // currently viewed folder actually changed (the reference inserts the new
  // rows into its JS list; our list is server-rendered).
  function initRefresh() {
    var mins = parseInt(document.body.getAttribute('data-refresh-interval') || '0', 10);
    if (!mins || !document.getElementById('messagelist')) return;
    var listEl = document.getElementById('messagelist');
    var currentFolder = (listEl && listEl.getAttribute('data-folder')) || '';
    function tick() {
      fetch('/mail/check-recent', {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var changed = false, inboxPrev = -1, inboxNow = 0;
          function badge(mbox) {
            var li = folderLi(mbox);
            var s = li && li.querySelector('span.unreadcount');
            return s ? parseInt(s.textContent, 10) || 0 : 0;
          }
          inboxPrev = badge('INBOX');
          var re = /this\.set_unread_count\((.*?)\);/g, m;
          var text = d.exec || '';
          while ((m = re.exec(text))) {
            var args = JSON.parse('[' + m[1] + ']');
            var mbox = String(args[0]), count = parseInt(args[1], 10) || 0;
            if (mbox === 'INBOX') inboxNow = count;
            // reload only when the visible folder's unread count moved
            if (mbox === currentFolder && folderLi(mbox) && badge(mbox) !== count)
              changed = true;
            setUnreadCount(mbox, count, !!args[2]);
          }
          if (inboxNow > inboxPrev && window.cc_display) {
            cc_display(inboxNow - inboxPrev === 1 ? 'You have 1 new message.'
                   : 'You have ' + (inboxNow - inboxPrev) + ' new messages.', 'info');
          }
          if (changed) {
            var url = new URL(location.href);
            // Elastic's check_mime_message reloads the list *with* the previewed
            // message (_uid stays in the request), so the content frame and the
            // focused row survive the refresh.
            var sel = document.querySelector('#messagelist tr.selected, #messagelist tr.focused');
            var uid = sel && sel.getAttribute('data-uid');
            if (uid) url.searchParams.set('_uid', uid);
            else url.searchParams.delete('_uid');
            location.href = url.toString();
          }
        })
        .catch(function () { /* offline session: next tick retries */ });
    }
    setInterval(tick, mins * 60000);
    window.cc_refresh_tick = tick; // exposed for tests
  }

  // --------------------------------------------- recipient_selector (ui.js):
  // "Add contact" opens the contacts list in a dialog; Insert appends the
  // selected addresses to the recipient field, comma-separated
  window.cc_recipient_dialog = function (field) {
    var d = cc_iframe_dialog('/contacts?_dialog=1&_source=0', cc_get_label('insertcontact'), 600, {
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

  // ------------------------------------------------ recipient autocomplete
  // rcmail autocomplete/ksearch on To/Cc/Bcc: debounced /mail/autocomplete
  // XHR (same endpoint/shape as the reference), dropdown insert replaces the
  // token under the caret. Elastic uses autocomplete_min_length=3.
  (function () {
    var inputs = document.querySelectorAll('textarea[data-recipient-input]');
    if (!inputs.length) return;
    var box = null, items = [], sel = -1, cur = null, timer = null, seq = 0;
    function ensureBox() {
      if (box) return box;
      box = document.createElement('div');
      box.className = 'cc-autocomplete hidden';
      box.style.cssText = 'position:absolute;z-index:1200;background:#fff;' +
        'border:1px solid #c7c7c7;border-radius:4px;max-height:220px;' +
        'overflow:auto;box-shadow:0 2px 8px rgba(0,0,0,.25);min-width:260px';
      document.body.appendChild(box);
      box.addEventListener('mousedown', function (e) {
        var li = e.target.closest && e.target.closest('li');
        if (li) { e.preventDefault(); pick(parseInt(li.getAttribute('data-i'), 10)); }
      });
      return box;
    }
    function tokenBefore(v, pos) {
      var s = v.slice(0, pos);
      var i = Math.max(s.lastIndexOf(','), s.lastIndexOf(';'), s.lastIndexOf('\n'));
      return {start: i + 1, text: s.slice(i + 1)};
    }
    function hide() {
      if (box) box.classList.add('hidden');
      items = []; sel = -1;
    }
    function render() {
      var b = ensureBox();
      b.innerHTML = '';
      items.forEach(function (c, i) {
        var li = document.createElement('li');
        li.textContent = c.name;
        li.setAttribute('data-i', i);
        li.style.cssText = 'padding:6px 10px;cursor:pointer;list-style:none' +
          (i === sel ? ';background:#e9f2fa' : '');
        li.addEventListener('mouseenter', function () { sel = i; render(); });
        b.appendChild(li);
      });
      var r = cur.getBoundingClientRect();
      b.style.left = r.left + window.scrollX + 'px';
      b.style.top = (r.bottom + window.scrollY + 2) + 'px';
      b.style.width = Math.max(r.width, 260) + 'px';
      b.classList.remove('hidden');
    }
    function pick(i) {
      var c = items[i];
      if (!c || !cur) return;
      var t = tokenBefore(cur.value, cur.selectionStart);
      var ins = (c.email || c.name) ? ((c.fields && c.fields.name && c.name.indexOf('<') > 0)
        ? c.name : (c.email || c.name)) : c.name;
      var after = cur.value.slice(cur.selectionStart);
      cur.value = cur.value.slice(0, t.start) + ins + (after.match(/^\s*,/) ? after : ', ' + after.replace(/^[,\s]+/, ''));
      var np = t.start + ins.length + 2;
      cur.setSelectionRange(np, np);
      hide();
      cur.focus();
    }
    function query() {
      if (!cur) return;
      var t = tokenBefore(cur.value, cur.selectionStart).text.trim();
      if (t.length < 3 || t.length > 120 || /^[0-9]/.test(t)) { hide(); return; }
      var mine = ++seq;
      fetch('/mail/autocomplete?_search=' + encodeURIComponent(t) + '&_reqid=' + mine,
            {headers: {'X-Requested-With': 'XMLHttpRequest'}})
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (mine !== seq || !cur) return;
          var text = d.exec || '';
          var i = text.indexOf('ksearch_query_results(');
          if (i < 0) { hide(); return; }
          var s = text.slice(i + 20), depth = 0, end = -1, inStr = false, esc = false;
          for (var j = 0; j < s.length; j++) {
            var ch = s[j];
            if (esc) { esc = false; continue; }
            if (ch === '\\') { esc = true; continue; }
            if (ch === '"') { inStr = !inStr; continue; }
            if (inStr) continue;
            if (ch === '[') depth++;
            else if (ch === ']') { depth--; if (!depth) { end = j; break; } }
          }
          try { items = JSON.parse(s.slice(0, end + 1)); } catch (e) { items = []; }
          // group entries need group_expand (not ported); skip like RC does
          // when a group has an email address
          items = items.filter(function (c) { return c.type !== 'group'; });
          if (!items.length) { hide(); return; }
          sel = 0;
          render();
        })
        .catch(function () {});
    }
    inputs.forEach(function (ta) {
      ta.addEventListener('keyup', function (e) {
        if (e.key === 'Escape') { hide(); return; }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp' ||
            e.key === 'Enter' || e.key === 'Tab') return;
        cur = ta;
        clearTimeout(timer);
        timer = setTimeout(query, 250);
      });
      ta.addEventListener('keydown', function (e) {
        if (!box || box.classList.contains('hidden') || !items.length) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % items.length; render(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; render(); }
        else if (e.key === 'Enter' && sel >= 0) { e.preventDefault(); pick(sel); }
        else if (e.key === 'Escape') { hide(); }
      });
      ta.addEventListener('blur', function () { setTimeout(hide, 200); });
    });
  })();

  // ---------------------------------------------------------------- search bar
  // Elastic ui.js behaviors for the quicksearch form: the unread toggle
  // switches #searchfilter between UNSEEN and ALL and submits; checking
  // "Entire message" disables the other modifiers; master checkboxes
  // (sender/recipient) sync their sub-lists.
  (function () {
    var form = document.getElementById('rcmqsearchform');
    if (!form) return;
    var filter = document.getElementById('searchfilter');
    var unread = document.querySelector('.searchbar a.button.unread');
    if (unread) {
      unread.addEventListener('click', function (e) {
        e.preventDefault();
        if (!filter) return;
        filter.value = filter.value === 'UNSEEN' ? 'ALL' : 'UNSEEN';
        unread.classList.toggle('selected', filter.value === 'UNSEEN');
        form.submit();
      });
    }
    function mods() {
      return Array.prototype.slice.call(
        form.querySelectorAll('input[type=checkbox][name=_sm]'));
    }
    function sync() {
      var by = {};
      mods().forEach(function (cb) { by[cb.value] = cb; });
      var disable = by.text && by.text.checked;
      ['subject', 'from', 'replyto', 'followupto', 'to', 'cc', 'bcc', 'body']
        .forEach(function (k) {
          if (by[k]) {
            by[k].disabled = !!disable;
            if (disable) by[k].parentNode.classList.toggle('disabled', true);
            else by[k].parentNode.classList.remove('disabled');
          }
        });
      [['sender', ['from', 'replyto', 'followupto']],
       ['recipient', ['to', 'cc', 'bcc']]].forEach(function (pair) {
        var master = by[pair[0]];
        if (!master) return;
        if (master.checked) {
          pair[1].forEach(function (k) { if (by[k]) by[k].checked = true; });
        }
        pair[1].forEach(function (k) {
          if (by[k] && !by[k].checked && master.checked) master.checked = false;
        });
      });
    }
    form.addEventListener('change', function (e) {
      if (e.target && e.target.name === '_sm') sync();
    });
    // expand master checkbox state on submit so SSR sees the sub-values too
    form.addEventListener('submit', function () { sync(); });
  })();
})();

// Elastic ui.js:1043 'tabbed' containers: turn fieldset legends into a
// bootstrap-style nav-tabs strip with one visible .tab-pane at a time.
(function () {
  function initTabs(root) {
    var containers = (root || document).querySelectorAll('form.tabbed, div.tabbed');
    Array.prototype.forEach.call(containers, function (item, idx) {
      if (item.getAttribute('data-tabbed')) return;
      item.setAttribute('data-tabbed', '1');
      var nav = document.createElement('ul');
      nav.className = 'nav nav-tabs';
      nav.setAttribute('role', 'tablist');
      var panes = [], links = [];
      Array.prototype.forEach.call(item.children, function (fieldset, i) {
        if (fieldset.tagName !== 'FIELDSET') return;
        var id = fieldset.id || ('tab' + idx + '-' + i);
        fieldset.id = id;
        fieldset.classList.add('tab-pane');
        fieldset.setAttribute('role', 'tabpanel');
        var legend = fieldset.querySelector('legend');
        var li = document.createElement('li');
        li.className = 'nav-item';
        var a = document.createElement('a');
        a.className = 'nav-link';
        a.setAttribute('role', 'tab');
        a.setAttribute('href', '#' + id);
        a.textContent = legend ? legend.textContent : id;
        if (legend) legend.style.display = 'none';
        a.addEventListener('click', function (e) {
          e.preventDefault();
          Array.prototype.forEach.call(links, function (l, j) {
            var on = l === a;
            l.classList.toggle('active', on);
            l.setAttribute('aria-selected', on ? 'true' : 'false');
            panes[j].classList.toggle('active', on);
          });
          return false;
        });
        li.appendChild(a);
        nav.appendChild(li);
        panes.push(fieldset);
        links.push(a);
      });
      if (!links.length) return;
      item.classList.add('tab-content');
      item.parentNode.insertBefore(nav, item);
      links[0].click();
    });
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function () { initTabs(); });
  else initTabs();

  // ------------------------------------------- mail list: refresh (ui.js
  // check_mail/checkmail: a persistent 'loading' info box while the request
  // runs, then the list re-renders in place) and Import (ui.js
  // mail_operation('import'): uploadform re-hosted in a dialog)
  function cc_hide_busy(key) {
    document.querySelectorAll('#messagestack div').forEach(function (el) {
      if (el.ccKey === key) window.cc_hide(el);
    });
  }
  // the compose page's GoogieSpell busy indicator shares the message stack
  window.cc_hide_busy = cc_hide_busy;
  window.cc_refresh_list = function (elem, event) {
    if (event) event.preventDefault();
    var url = (elem && elem.getAttribute('href')) || window.location.href;
    var key = window.cc_display(cc_get_label('loading') || 'Loading...', 'loading', 30000);
    fetch(url, { credentials: 'same-origin',
                 headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var freshBody = doc.querySelector('#messagelist tbody');
        var curBody = document.querySelector('#messagelist tbody');
        if (!freshBody || !curBody) { window.location.href = url; return; }
        curBody.innerHTML = freshBody.innerHTML;
        // page navigator state (disabled links, page text, jumper)
        var freshNav = doc.querySelector('.pagenav');
        var curNav = document.querySelector('.pagenav');
        if (freshNav && curNav) curNav.innerHTML = freshNav.innerHTML;
        // sidebar unread counts (reference check_mail also re-renders the
        // tree); fold state is re-applied over the fresh nodes
        var freshTree = doc.querySelector('#mailboxlist');
        var curTree = document.getElementById('mailboxlist');
        if (freshTree && curTree) {
          curTree.innerHTML = freshTree.innerHTML;
          cc_apply_folds(curTree);
        }
        cc_hide_busy(key);
      })
      .catch(function () { cc_hide_busy(key); window.location.href = url; });
    return false;
  };

  window.cc_import_dialog = function (event) {
    if (event) event.preventDefault();
    var src = document.getElementById('uploadform');
    if (!src) return false;
    // ui.js: the uploadform popup is shown as a modal dialog titled
    // 'Import messages' with the import button
    var form = src.cloneNode(true);
    form.removeAttribute('id');
    form.classList.remove('popupmenu', 'open', 'inactive');
    // the real <form> lives inside the cloned #uploadform div
    var formEl = form.tagName === 'FORM' ? form : form.querySelector('form');
    if (formEl) formEl.removeAttribute('id');
    var inp = form.querySelector('input[type=file]');
    if (inp) {
      inp.id = 'uploadformInput-clone';
      var lbl = form.querySelector('label[for="uploadformInput"]');
      if (lbl) lbl.setAttribute('for', 'uploadformInput-clone');
    }
    var dlg = ccDialog(form, cc_get_label('importmessages') || 'Import messages', {
      width: 530,
      buttons: [
        { label: cc_get_label('import') || 'Import', cls: 'mainaction import',
          click: function () {
            if (!inp || !inp.files || !inp.files.length) {
              // ui.js upload_import(): 'Please select a file to upload.'
              window.cc_display(cc_get_label('selectimportfile'), 'error');
              return;
            }
            window.cc_display(cc_get_label('loading') || 'Loading...', 'loading', 120000);
            // submit first: close() would detach the form from the
            // document and the submission would silently no-op
            (formEl || form).submit();
          } },
        { label: cc_get_label('cancel') || 'Cancel', cls: 'cancel',
          click: function () { dlg.close(); } },
      ],
    });
    window.cc_close_popups && window.cc_close_popups();
    return false;
  };

  // ------------------------------------------- mailbox tree fold state
  // (reference persists fold in user prefs; craftcube has no server-side
  // fold storage, so keep it per browser via localStorage)
  function cc_apply_folds(root) {
    var folds = {};
    try { folds = JSON.parse(localStorage.getItem('cc-mailbox-fold') || '{}'); } catch (e) {}
    root.querySelectorAll('li[data-name]').forEach(function (li) {
      var t = li.querySelector('.treetoggle');
      if (!t || t.parentNode !== li) return;
      if (folds[li.getAttribute('data-name')]) setFold(li, t, true);
    });
  }
  function setFold(li, t, collapsed) {
    var ul = null;
    for (var i = 0; i < li.children.length; i++) {
      if (li.children[i].tagName === 'UL') { ul = li.children[i]; break; }
    }
    t.classList.toggle('expanded', !collapsed);
    t.classList.toggle('collapsed', !!collapsed);
    li.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    if (ul) ul.style.display = collapsed ? 'none' : '';
  }
  function initMailboxFold() {
    var mlist = document.getElementById('mailboxlist');
    if (!mlist) return;
    cc_apply_folds(mlist);
    mlist.addEventListener('click', function (e) {
      var t = e.target.closest('.treetoggle');
      if (!t) return;
      e.preventDefault();
      e.stopPropagation();
      var li = t.parentNode;
      var collapsed = !t.classList.contains('collapsed');
      setFold(li, t, collapsed);
      var folds = {};
      try { folds = JSON.parse(localStorage.getItem('cc-mailbox-fold') || '{}'); } catch (err) {}
      folds[li.getAttribute('data-name')] = collapsed;
      try { localStorage.setItem('cc-mailbox-fold', JSON.stringify(folds)); } catch (err) {}
    });
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function () { initMailboxFold(); });
  else initMailboxFold();
})();

/* Reference elastic ui.js: "Convert checkbox input into Bootstrap's custom
   switch" (pretty_checkbox) — applied to propforms, form-checks, popup
   forms, menus and [data-list] checkboxes; framed editor pages focus the
   first text input like the reference content-frame flow. */
(function () {
  var seq = 0;
  // ui.js: var supported_controls = 'input:not(.button,.no-bs,[type=button],
  //   [type=radio],[type=checkbox],[type=file]),textarea'
  var SUPPORTED = 'input:not(.button):not(.no-bs):not([type=button]):not([type=radio])' +
    ':not([type=checkbox]):not([type=file]),textarea';
  function isSupported(el) {
    var m = el.matches || el.msMatchesSelector;
    return m.call(el, SUPPORTED);
  }
  // ui.js "Make propforms bootstrap-like": rows get form-group row, title
  // cells col-sm-4, control cells col-sm-8, inputs form-control — but cells
  // that already carry a col-sm-* class (e.g. the encryption section's
  // cols-sm-6-6 rows, where the classes come from the template like in RC)
  // are left alone; double classes made the td 2/3 wide and overflowed.
  function has_col(el) {
    return /\bcol-sm-\d\b/.test(el.className);
  }
  function beautifyPropform(table) {
    var rows = table.querySelectorAll(':scope > tbody > tr, :scope > tr');
    var text_rows = 0, form_rows = 0;
    rows.forEach(function (row) {
      var cells = row.children;
      if (cells.length === 2) {
        var first = cells[0], last = cells[1];
        var lab = first.querySelector('label');
        if (lab) { lab.classList.add('col-form-label'); }
        if (!has_col(first)) { first.classList.add('col-sm-4'); }
        if (!has_col(last)) { last.classList.add('col-sm-8'); }
        row.classList.add('form-group', 'row');
        var inputs = last.querySelectorAll('input:not([type=hidden]),textarea,select');
        if (last.querySelectorAll('input[type=checkbox]').length === 1 &&
            !last.querySelector('.proplist')) {
          row.classList.add('form-check');
          if (last.querySelector('a')) { row.classList.add('with-link'); }
          form_rows++;
        } else if (!inputs.length) {
          last.classList.add('form-control-plaintext');
          text_rows++;
        } else {
          form_rows++;
        }
      } else if (cells.length === 1) {
        cells[0].style.width = '100%';
      }
    });
    if (text_rows > form_rows) { table.classList.add('text-only'); }
  }
  function pretty(checkbox) {
    if (checkbox.classList.contains('custom-control-input')) { return; }
    var id = checkbox.id;
    if (!id) { id = 'icochk' + (++seq); checkbox.id = id; }
    var label;
    if (checkbox.parentElement.tagName === 'LABEL') {
      label = checkbox.parentElement;
      label.parentNode.insertBefore(checkbox, label);
    } else {
      label = document.createElement('label');
    }
    label.setAttribute('for', id);
    label.className = 'custom-control-label';
    if (checkbox.title) { label.title = checkbox.title; }
    label.addEventListener('click', function (e) { e.stopPropagation(); });
    var wrap = document.createElement('div');
    wrap.className = 'custom-control custom-switch';
    checkbox.classList.add('form-check-input', 'custom-control-input');
    checkbox.parentNode.insertBefore(wrap, checkbox);
    wrap.appendChild(checkbox);
    wrap.appendChild(label);
  }
  // elastic ui.js:3627-3647 image_upload_input: append the reset overlay to
  // the .image-upload widget, toggle 'changed' from the placeholder state
  // and open the hidden smart-upload picker on click
  function enableSave() {
    var b = document.querySelector('#contact-details ~ .formbuttons button.submit, .formbuttons button.submit[form=contact-details]');
    if (b) { b.disabled = false; }
  }
  function imageUploadWidget(obj) {
    var img = obj.querySelector('img');
    var placeholder = obj.getAttribute('data-placeholder') || '';
    var btn = document.createElement('a');
    btn.className = 'icon button delete';
    btn.href = '#';
    btn.addEventListener('click', function (e) {
      // rcmail.command('delete-photo') -> replace_contact_photo('-del-'):
      // marker + placeholder only, the removal is applied on save
      e.preventDefault();
      e.stopPropagation();
      var ff = document.getElementById('ff_photo');
      if (ff) { ff.value = '-del-'; }
      var file = document.getElementById('ff_photo_file');
      if (file) { file.value = ''; }
      if (img) { img.src = placeholder; }
      enableSave();
    });
    obj.appendChild(btn);
    obj.addEventListener('click', function () {
      var inp = document.getElementById('upload-formInput');
      if (inp) { inp.click(); }
    });
    // rcube_dragdrop 'filedrop' (rcmail.gui_object('filedrop', 'contactpic')):
    // a dropped image uploads like a picked one (filter ^image/.+)
    obj.addEventListener('dragover', function (e) {
      e.preventDefault();
      obj.classList.add('droptarget');
    });
    obj.addEventListener('dragleave', function () {
      obj.classList.remove('droptarget');
    });
    obj.addEventListener('drop', function (e) {
      e.preventDefault();
      obj.classList.remove('droptarget');
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file && file.type.indexOf('image/') === 0) { pickFile(file); }
    });
    if (img) {
      var state = function () {
        var is_ph = (img.currentSrc || img.src || '').indexOf(placeholder) !== -1;
        obj.classList[is_ph ? 'remove' : 'add']('changed');
      };
      img.addEventListener('load', state);
      state();
    }
  }
  function pickFile(file) {
    // shared entry for the smart-upload input and the rcube_dragdrop target
    var frm = document.getElementById('upload-formFrm');
    var cidEl = frm && frm.querySelector('input[name=_cid]');
    var cid = cidEl ? cidEl.value : '';
    if (cid) {
      // rcmail.command('upload-photo'): uploads right away
      var fd = new FormData();
      fd.append('_upload', '1');
      fd.append('_cid', cid);
      fd.append('_photo', file, 'photo');
      fetch(location.pathname + '?_framed=' + (location.search.indexOf('_framed=1') > -1 ? '1' : '0'),
        { method: 'POST', body: fd }).then(function () { location.reload(); });
      return;
    }
    // new contact (rcmail temp-upload id equivalent): hand the file to
    // the main editform and preview it like replace_contact_photo()
    var dst = document.getElementById('ff_photo_file');
    if (dst) {
      try {
        var dt = new DataTransfer();
        dt.items.add(file);
        dst.files = dt.files;
      } catch (e) {}
    }
    var ff = document.getElementById('ff_photo');
    if (ff) { ff.value = ''; }
    var pic = document.getElementById('contactpic');
    var img = pic && pic.querySelector('img');
    if (img) { img.src = URL.createObjectURL(file); }
    enableSave();
  }
  function wireUploadForm() {
    var inp = document.getElementById('upload-formInput');
    var frm = document.getElementById('upload-formFrm');
    if (!inp || !frm) { return; }
    inp.addEventListener('change', function () {
      if (!inp.files.length) { return; }
      pickFile(inp.files[0]);
    });
  }
  function run() {
    // ui.js order: bootstrap classes, propform row beautification, then
    // pretty switches. Rows already carrying col-* classes (templates
    // ported from live reference DOM) are skipped.
    document.querySelectorAll('.propform ' + SUPPORTED).forEach(function (el) {
      el.classList.add('form-control');
    });
    document.querySelectorAll('.propform input[type=checkbox]').forEach(function (el) {
      el.classList.add('form-check-input');
    });
    document.querySelectorAll('table.propform').forEach(function (table) {
      var rows = table.querySelectorAll(':scope > tbody > tr, :scope > tr');
      var done = rows.length && rows[0].classList.contains('col-sm-4');
      var done2 = rows.length && Array.prototype.some.call(rows[0].children, function (c) {
        return c.classList.contains('col-sm-4') || c.classList.contains('col-sm-6') ||
               c.classList.contains('col-sm-8');
      });
      if (!done && !done2) { beautifyPropform(table); }
    });
    // ui.js:975-985 "Other forms, e.g. Contact advanced search": head rows
    // (label + control div) get the bootstrap column grid
    document.querySelectorAll('fieldset.propform:not(.grouped) div.row').forEach(function (row) {
      if (row.classList.contains('form-group')) { return; }
      var kids = row.children;
      if (!kids.length) { return; }
      var has_input = row.querySelector('input:not([type=hidden]),select,textarea') !== null;
      if (has_input) {
        row.querySelectorAll(SUPPORTED).forEach(function (el) { el.classList.add('form-control'); });
      }
      kids[kids.length - 1].classList.add('col-sm-8');
      if (!has_input) { kids[kids.length - 1].classList.add('form-control-plaintext'); }
      kids[0].classList.add('col-sm-4', 'col-form-label');
      row.classList.add('form-group');
    });
    // ui.js:988-1019 "Contact info/edit form": grouped fieldset rows become
    // bootstrap input-groups (subtype select or label as prepend, delete
    // button in an append span); JS-inserted cc-tpl rows carry these
    // classes already and are skipped
    document.querySelectorAll('fieldset.propform.grouped fieldset').forEach(function (fs) {
      fs.querySelectorAll('.row').forEach(function (row) {
        if (row.classList.contains('input-group')) { return; }
        var kids = Array.prototype.slice.call(row.children);
        var has_input = row.querySelector('input,select,textarea') !== null;
        if (has_input) {
          row.querySelectorAll(SUPPORTED).forEach(function (el) { el.classList.add('form-control'); });
        }
        if (kids.length < 2) { return; }
        var first = kids[0];
        if (first.tagName === 'SELECT') {
          first.classList.add('input-group-prepend');
        } else {
          var pre = document.createElement('span');
          pre.className = 'input-group-prepend';
          first.parentNode.insertBefore(pre, first);
          pre.appendChild(first);
          first.classList.add('input-group-text');
        }
        if (!has_input) { kids[kids.length - 1].classList.add('form-control-plaintext'); }
        var content = row.querySelector('.content');
        if (content) { content.classList.add('input-group-prepend', 'input-group-append', 'input-group-text'); }
        var del = row.querySelector('a.deletebutton');
        if (del) {
          del.classList.add('input-group-text', 'icon', 'delete');
          var app = document.createElement('span');
          app.className = 'input-group-append';
          del.parentNode.insertBefore(app, del);
          app.appendChild(del);
        }
        row.classList.add('input-group');
      });
    });
    document.querySelectorAll(
      'input.pretty-checkbox, .propform input[type=checkbox], ' +
      '.form-check input[type=checkbox], .popupmenu.form input[type=checkbox], ' +
      '.menu input[type=checkbox], [data-list] input[type=checkbox]'
    ).forEach(pretty);
    document.querySelectorAll('.image-upload').forEach(imageUploadWidget);
    wireUploadForm();
    // elastic: the contact editor's Save stays disabled while the form is
    // unchanged (rcmail check_stack); any edit enables it
    var ef = document.getElementById('contact-details');
    if (ef) {
      ef.addEventListener('input', enableSave);
      ef.addEventListener('change', enableSave);
    }
    // framed editors land with the first text field focused (elastic)
    if (window.top !== window.self) {
      var f = document.querySelector(
        '.formcontent input[type=text]:not([disabled]):not([type=hidden]), ' +
        '.formcontent textarea');
      if (f && f.offsetParent) {
        f.focus();
        try { f.select(); } catch (e) {}
      }
      // parent.update_identity_row/update_response_row (app.js:7718-7737):
      // a framed save syncs the parent list row (insert+select on create)
      var sm = location.search.match(/[?&]_saved=(\w+)/);
      if (sm && window.parent.cc_settings_row_upsert) {
        var idm = location.pathname.match(/\/edit\/(\d+)/);
        var ne = document.querySelector('input[name=_name]');
        if (idm && ne) {
          window.parent.cc_settings_row_upsert({
            list: /\/settings\/response\//.test(location.pathname)
              ? '#responses-table' : '#identities-table',
            id: idm[1], name: ne.value, add: sm[1] === 'insert'
          });
        }
      }
    }
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', run); }
  else { run(); }
})();

/* Reference elastic ui.js ui_common(): "Move form buttons from the content
   frame into the frame footer (on parent window)". The parent gets a
   .content-frame-navigation footer bar (prev / .buttons / next); CSS hides
   the whole bar at >=769px, so on desktop the in-frame .formbuttons stay
   visible. Only phone/small layouts surface the clones. */
(function () {
  function ensureFrameNav() {
    var lc = document.getElementById('layout-content');
    if (!lc || lc.classList.contains('no-navbar')) { return null; }
    if (lc.querySelector(':scope > .frame-content')) { return null; }
    var fn = lc.querySelector(':scope > .content-frame-navigation');
    if (!fn) {
      fn = document.createElement('div');
      fn.className = 'footer menu toolbar content-frame-navigation hide-nav-buttons';
      fn.innerHTML = '<a class="button prev"><span class="inner"></span></a>' +
        '<span class="buttons"></span>' +
        '<a class="button next"><span class="inner"></span></a>';
      lc.appendChild(fn);
    }
    return fn;
  }

  function cloneInto(lcRoot, defs, frameWin) {
    var fn = ensureFrameNav();
    if (!fn) { return; }
    var tb = fn.querySelector('.buttons');
    Array.prototype.slice.call(tb.querySelectorAll('[data-cc-cloned]'))
      .forEach(function (n) { n.remove(); });
    defs.forEach(function (d, i) {
      var a = document.createElement('a');
      a.href = '#';
      // ui.js create_cloned_button class transform: btn-primary -> primary,
      // strip btn*/button/disabled, add button
      a.className = (d.cls || '').replace('btn-primary', 'primary')
        .replace(/(btn[a-z-]*|button|disabled)/g, '').trim() + ' button';
      a.setAttribute('data-cc-cloned', '1');
      var s = document.createElement('span');
      s.className = 'inner';
      s.textContent = d.label;
      a.appendChild(s);
      a.addEventListener('click', function (e) {
        e.preventDefault();
        try { frameWin.cc_content_button_click(i); } catch (err) {}
      });
      tb.appendChild(a);
    });
  }

  function collect(buttons) {
    var visible = [];
    buttons.forEach(function (b) {
      if (b.classList.contains('cancel')) { b.classList.add('hidden'); return; }
      visible.push(b);
    });
    return visible;
  }

  if (window.top === window.self) {
    // parent page: framed pages register their buttons here
    window.cc_register_content_buttons = function (frameWin, defs) {
      cloneInto(null, defs, frameWin);
    };
    // full-page forms: clone own #layout-content .formbuttons into header
    function initSelf() {
      var content = document.querySelector('#layout-content.selected') ||
                    document.querySelector('#layout-content');
      if (!content) { return; }
      var box = null;
      content.querySelectorAll('.formbuttons').forEach(function (x) {
        if (box || x.classList.contains('cc-cloned')) { return; }
        if (x.closest('.searchoptions, .popupmenu, .searchbar')) { return; }
        box = x;
      });
      if (!box) { return; }
      var buttons = Array.prototype.slice.call(
        box.querySelectorAll('button, a.btn-primary'));
      var visible = collect(buttons);
      if (!visible.length) { return; }
      window.cc_content_button_click = function (i) { visible[i].click(); };
      var defs = visible.map(function (b) {
        return { label: (b.textContent || '').trim() || 'Save', cls: b.className };
      });
      cloneInto(null, defs, window);
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', initSelf); }
    else { initSelf(); }
    return;
  }

  // framed side
  function init() {
    // ui.js: body of a framed page with .formcontent + .formbuttons gets
    // .formcontainer (flex column: scrolling form, bottom button bar)
    var fc = document.querySelector('.formcontent');
    if (fc && fc.parentElement.querySelector('.formbuttons')) {
      fc.parentElement.classList.add('formcontainer');
    }
    var buttons = Array.prototype.slice.call(
      document.querySelectorAll('.formbuttons button, .formbuttons a.btn-primary'));
    if (!buttons.length || !window.parent.cc_register_content_buttons) { return; }
    var visible = collect(buttons);
    if (!visible.length) { return; }
    window.cc_content_button_click = function (i) { visible[i].click(); };
    var defs = visible.map(function (b) {
      return { label: (b.textContent || '').trim() || 'Save', cls: b.className };
    });
    window.parent.cc_register_content_buttons(window, defs);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
