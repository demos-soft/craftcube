/*
 * Info boxes — port of Roundcube's message stack.
 * program/js/app.js display_message()/hide_message() plus the elastic skin's
 * alert_style() decoration (skins/elastic/ui.js:1990-2033):
 *   - container div#messagestack (gui object 'message')
 *   - each box: <div class="{type} content ui alert alert-X"><i class="icon">
 *     <span>text</span></div>, role=alert, click to dismiss
 *   - default timeout 5000ms (message_time); error/warning get 2x.
 *     RC quirk: an explicit 0 is falsy in JS, so server-emitted
 *     display_message(msg,"warning",0) still auto-hides after 10s.
 *   - identical messages are deduped by key (message text)
 *   - framed pages forward to the parent window (app.js is_framed branch)
 */
(function () {
  'use strict';
  var MESSAGE_TIME = 5000;
  var ALERTS = {
    information: 'alert-info',
    notice: 'alert-info',
    confirmation: 'alert-success',
    warning: 'alert-warning',
    error: 'alert-danger',
    loading: 'alert-info loading',
    uploading: 'alert-info loading'
  };
  var messages = {};

  function hide(el) {
    if (!el || el.ccHidden) return;
    el.ccHidden = true;
    el.style.transition = 'opacity .5s';
    el.style.opacity = '0';
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
      var k = el.getAttribute('data-key');
      if (k && messages[k]) delete messages[k];
    }, 600);
  }

  function display(msg, type, timeout) {
    // app.js: framed pages pass the command to the parent window
    if (window.top !== window.self && window.parent.cc_display) {
      return window.parent.cc_display(msg, type, timeout);
    }
    if (!msg || !msg.length) return null;
    if (!type) type = 'notice';
    var stack = document.getElementById('messagestack');
    if (!stack) {
      window.cc_pending = window.cc_pending || [];
      if (type !== 'loading') window.cc_pending.push([msg, type, timeout]);
      return 1;
    }
    if (!timeout) {
      timeout = (type === 'error' || type === 'warning') ? MESSAGE_TIME * 2 : MESSAGE_TIME;
    }
    var key = msg.replace(/\s+/g, '_').replace(/[^A-Za-z0-9_]/g, '');
    if (messages[key]) {
      if (messages[key].span) messages[key].span.innerHTML = msg; // replace label
      messages[key].count++;
      return key;
    }
    var el = document.createElement('div');
    el.className = type + ' content';
    el.textContent = msg;
    // elastic alert_style(): content wrapped in <span> for icon alignment
    var span = document.createElement('span');
    while (el.firstChild) span.appendChild(el.firstChild);
    el.appendChild(span);
    var alertCls = ALERTS[type.split(' ')[0]];
    if (alertCls) {
      var icon = document.createElement('i');
      icon.className = 'icon';
      el.insertBefore(icon, el.firstChild);
      el.className += ' ui alert ' + alertCls;
    }
    el.setAttribute('role', 'alert');
    el.setAttribute('data-key', key);
    el.addEventListener('click', function () { hide(el); });
    stack.appendChild(el);
    messages[key] = { el: el, span: el.querySelector('span'), count: 1 };
    if (timeout > 0) setTimeout(function () { hide(el); }, timeout);
    return key;
  }

  window.cc_display = display;
  window.cc_hide = hide;

  function drain() {
    var pend = window.cc_pending || [];
    window.cc_pending = [];
    pend.forEach(function (m) { display(m[0], m[1], m[2]); });
    // server-side flash bridge (templates emit window.CC_FLASHES)
    (window.CC_FLASHES || []).forEach(function (m) { display(m[1], m[0], 0); });
  }
  if (document.readyState !== 'loading') drain();
  else document.addEventListener('DOMContentLoaded', drain);
})();
