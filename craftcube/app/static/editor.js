/**
 * CraftCube editor — vanilla port of Roundcube's rcube_text_editor
 * (program/js/editor.js), the Elastic skin's editor hookup
 * (skins/elastic/ui.js: html_editor_init, tinymce_init, plaintext button)
 * and the app.js command side (editor_init, toggle_editor, format_converter).
 *
 * Structure per editor (as rendered by our templates):
 *   <div class="html-editor">
 *     <textarea data-html-editor>           (id = editorId)
 *     <div class="editor-toolbar"><a class="mce-i-html">   (created here)
 *     <select class="hidden"> | <input type=checkbox>      (mode switch)
 *   </div>
 */
(function (window, document) {
  'use strict';

  // ----------------------------------------------------------------- helpers
  function byId(id) { return document.getElementById(id); }
  function closest(el, sel) { return el.closest(sel); }

  // rcmail.get_label / gettext for the handful of strings we need
  var env = { signatures: {}, identities: {}, editor_config: {} };
  var LABELS = {
    htmltoggle: 'HTML',
    plaintoggle: 'Plain text',
    converting: 'Converting...',
    editorwarning: 'Switching editor type may cause text formatting to be lost. Do you wish to continue?'
  };
  function get_label(k) { return LABELS[k] || k; }

  // rcmail.set_busy() equivalent: a small fixed overlay with the label
  var busy_layer = null;
  function set_busy(on, label) {
    if (busy_layer) { busy_layer.remove(); busy_layer = null; }
    if (!on) return null;
    busy_layer = document.createElement('div');
    busy_layer.className = 'cc-busy';
    busy_layer.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;' +
      'background:rgba(255,255,255,.6);z-index:2000;display:flex;' +
      'align-items:center;justify-content:center;font-weight:bold';
    busy_layer.textContent = label || '';
    document.body.appendChild(busy_layer);
    return busy_layer;
  }

  // rcube_find_object
  function find_object(id) { return byId(id); }

  // rcmail.get_input_selection
  function get_input_selection(el) {
    var result = { start: 0, end: 0, text: '' };
    try {
      if (typeof el.selectionStart === 'number') {
        result.start = el.selectionStart;
        result.end = el.selectionEnd;
        result.text = el.value.substring(result.start, result.end);
      }
    } catch (e) { /* not a text field */ }
    return result;
  }

  // rcmail.set_caret_pos
  function set_caret_pos(el, pos) {
    if (!el) return;
    if (el.setSelectionRange) {
      el.focus();
      el.setSelectionRange(pos, pos);
    }
  }

  // rcmail.quote_html
  function quote_html(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;')
      .replace(/\n/g, '<br />');
  }

  // textarea_autoresize_init (ui.js): grow with content, no scrollbar
  function textarea_autoresize_init(textarea) {
    var padding; var minHeight;
      var resize = function () {
        if (!textarea.scrollHeight) return setTimeout(resize, 250);
        if (!padding) {
          var cs = window.getComputedStyle(textarea);
          padding = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + 2;
          minHeight = textarea.offsetHeight;
        }
        if (textarea.scrollHeight - padding <= minHeight) return;
        var scroll_element = null; var scroll_pos = 0;
        for (var p = textarea.parentNode; p; p = p.parentNode) {
          if (p.scrollTop > 0) { scroll_element = p; scroll_pos = p.scrollTop; break; }
        }
        var oldHeight = textarea.offsetHeight;
        textarea.style.height = '0';
        var newHeight = Math.max(minHeight, textarea.scrollHeight);
        textarea.style.height = '';
        if (newHeight !== oldHeight) textarea.style.height = newHeight + 'px';
        if (scroll_pos) scroll_element.scrollTop = scroll_pos;
      };
    textarea.addEventListener('input', resize);
    setTimeout(resize, 100);
  }

  // ---------------------------------------------------------------- converter
  // rcmail.format_converter + plain2html/html2plain (app.js:8923-8970)

  function format_converter(text, format, func) {
    // warn the user (if converted content is not empty)
    if (!text
      || (format === 'html' && !(text.replace(/<[^>]+>|&nbsp;|\u00C2\u00A0|\s/g, '')).length)
      || (format !== 'html' && !(text.replace(/\u00C2\u00A0|\s/g, '')).length)
    ) {
      if (func) setTimeout(function () { func(''); }, 50);
      return true;
    }

    var confirmed = env.editor_warned || confirm(get_label('editorwarning'));
    env.editor_warned = true;
    if (!confirmed) return false;

    var url = (format === 'html' ? '/utils/html2text' : '/utils/text2html');
      var lock = set_busy(true, get_label('converting'));

    var xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.onerror = function () { if (lock) set_busy(false); };
    xhr.onload = function () {
      if (lock) set_busy(false);
      if (func && xhr.status === 200) func(xhr.responseText);
    };
    xhr.send(text);
    return true;
  }

  // ------------------------------------------------------------- editor class
  // rcube_text_editor (editor.js), jQuery-free
  function rcube_text_editor(config, id) {
    var ref = this;
      var editorElement = byId(id);
      var abs_url = location.href.replace(/[?#].*$/, '').replace(/\/$/, '');
      var conf = {
        selector: '#' + (editorElement.classList.contains('mce_editor') ? id : 'fake-editor-id'),
        readonly: editorElement.hasAttribute('readonly') || editorElement.disabled,
        cache_suffix: 's=5080200',
        theme: 'silver',
        language: config.lang,
        content_css: config.content_css,
        content_style: config.content_style,
        menubar: false,
        statusbar: false,
        toolbar_drawer: 'sliding',
        toolbar: 'bold italic underline | alignleft aligncenter alignright alignjustify'
          + ' | fontselect fontsizeselect | forecolor backcolor',
        extended_valid_elements: 'font[face|size|color|style],span[id|class|align|style]',
        fontsize_formats: '8pt 9pt 10pt 11pt 12pt 14pt 18pt 24pt 36pt',
        valid_children: '+body[style],+blockquote[style],+div[style]',
        relative_urls: false,
        remove_script_host: false,
        convert_urls: false,
        image_description: false,
        paste_webkit_styles: 'color font-size font-family font-weight background-color',
        automatic_uploads: false,
        paste_data_images: true,
        browser_spellcheck: true,
        contextmenu: 'spellchecker',
        anchor_bottom: false,
        anchor_top: false,
        file_picker_types: 'image media',
        min_height: config.mode === 'identity' ? 100 : 400,
        deprecation_warnings: false
      };

    this.spellcheck_observer = function () {};

    // spellchecker RPC (editor.js: spellchecker_rpc_url + language)
    if (config.spellcheck) {
      this.spell_rpc = (window.CC_ENV && CC_ENV.comm_spell) || '/utils/spell_html';
    }

    // minimal editor (identity/response) vs full-featured (compose)
    if (config.mode === 'identity' || config.mode === 'response') {
      conf.toolbar += ' | charmap hr link unlink image code $extra';
      conf.plugins = 'autolink charmap code hr image link paste tabfocus';
      conf.file_picker_types = 'image';
    } else {
      conf.toolbar += ' | bullist numlist outdent indent ltr rtl blockquote'
        + ' | link unlink table | $extra charmap image media | code searchreplace undo redo';
      conf.plugins = 'autolink charmap code directionality link lists image media nonbreaking'
        + ' paste table tabfocus searchreplace';
      if (config.spellcheck) {
        conf.plugins += ' spellchecker';
        conf.spellchecker_rpc_url = this.spell_rpc;
        conf.spellchecker_language = env.spell_lang || 'en';
      }
    }

    conf.disabled_plugins = config.disabled_plugins || [];
    conf.disabled_buttons = config.disabled_buttons || [];
    conf.extra_plugins = config.extra_plugins || [];
    conf.extra_buttons = config.extra_buttons || [];

    // ui.js tinymce_init(): Enable autoresize plugin
    conf.plugins += ' autoresize';

    // Elastic plaintext button first (ui.js:1403) — only inside .html-editor
    var is_editor = closest(editorElement, '.html-editor');
    if (is_editor) {
      conf.toolbar = 'plaintext | ' + conf.toolbar;
      conf.setup_callback = function (ed) {
        ed.ui.registry.addButton('plaintext', {
          tooltip: get_label('plaintoggle'),
          icon: 'close',
          onAction: function (e) {
            if (cc_toggle_editor({ id: ed.id, html: false })) {
              closest(byId(ed.id), '.html-editor').classList.remove('ishtml');
            }
          }
        });
      };
    }

    // $extra cleanup (editor.js; $font not present in this TinyMCE build)
    conf.extra_buttons.forEach(function (b) {
      if (conf.toolbar.indexOf(b) < 0) conf.toolbar = conf.toolbar.replace('$extra', '$extra ' + b);
    });
    conf.disabled_buttons.forEach(function (b) { conf.toolbar = conf.toolbar.replace(b, ''); });
    conf.toolbar = conf.toolbar.replace(/\$extra/, '').replace(/\|\s+\|/g, '|');

    conf.setup = function (ed) {
      ed.on('init', function () { ref.init_callback(ed); });
      // spellcheck button state update (editor.js setup)
      ed.on('SpellcheckStart SpellcheckEnd', function (args) {
        ref.spellcheck_active = args.type === 'spellcheckstart';
        ref.spellcheck_observer();
      });
      // make links open on shift-click
      ed.on('click', function (e) {
        var link = closest(e.target, 'a');
        if (link && e.shiftKey) {
          window.open(link.href, '_blank');
          e.preventDefault();
          return false;
        }
      });
      ed.on('focus blur', function () {
        ed.getContainer().classList.toggle('focused');
      });
      if (conf.setup_callback) conf.setup_callback(ed);
    };

    // textarea identifier
    this.id = id;
    // reference to active editor (if in HTML mode)
    this.editor = null;

    tinymce.init(conf);

    // react to real individual TinyMCE init
    this.init_callback = function (editor) {
      this.editor = editor;
      if (env.action === 'compose') {
        var area = editorElement;
          var group = editorElement.parentNode.querySelector('div.tox-toolbar__group');
        // jQuery .height() also measures display:none elements (rows *
        // line-height), unlike offsetHeight; without this the wait-loop
        // below never ends once the textarea is hidden by the editor
        var area_h = area.offsetHeight || (area.rows * (parseFloat(getComputedStyle(area).lineHeight) || 0));
        var height = group ? group.offsetHeight : 0;
        // editor might still be loading; retry like the reference (#1490310)
        if (height > 200 || (group && height > area_h)) {
          return setTimeout(function () { ref.init_callback(editor); }, 300);
        }
      }
      // set tabIndex and focus previously focused element
      this.tabindex(this.force_focus);
    };

    this.tabindex = function (focus) {
      if (env.task === 'mail' && this.editor) {
        var textarea = this.editor.getElement();
          var node = this.editor.getContentAreaContainer().childNodes[0];
        if (textarea && node && textarea.tabIndex >= 0) node.tabIndex = textarea.tabIndex;
      }
      if (focus) this.focus();
    };

    this.focus = function () {
      (this.editor || editorElement).focus();
      this.force_focus = false;
    };

    this.is_html = function () { return !!this.editor; };

    // switch html/plain mode (editor.js toggle())
    this.toggle = function (ishtml, noconvert) {
      var curr; var content; var result;
        // non-printable chars survive text2html/html2text as sig placeholder
        var sig_mark = '\u0002\u0003';
        var input = editorElement;
        var signature = env.identity ? env.signatures[env.identity] : null;
        var is_sig = signature && signature.text && signature.text.length > 1;

      if (ishtml) {
        content = input.value;

        if (is_sig) {
          content = content.replace(/\r\n/, '\n');
          content = content.replace(signature.text.replace(/\r\n/, '\n'), sig_mark);
        }

        var init_editor = function (data) {
          if (is_sig) data = data.replace(sig_mark, '<div id="_rc_sig">' + signature.html + '</div>');
          ref.force_focus = true;
          input.value = data;
          tinymce.execCommand('mceAddEditor', false, ref.id);
        };

        if (!noconvert) result = format_converter(content, 'plain', init_editor);
        else { init_editor(content); result = true; }
      } else if (this.editor) {
        if (is_sig) {
          var sigEl = this.editor.dom.get('_rc_sig');
          if (sigEl) curr = sigEl.innerHTML;
          if (sigEl) sigEl.innerHTML = sig_mark;
        }

        content = this.editor.getContent();

        var init_plaintext = function (data) {
          tinymce.execCommand('mceRemoveEditor', false, ref.id);
          ref.editor = null;
          if (is_sig) data = data.replace(sig_mark, '\n' + signature.text);
          input.value = data;
          input.focus();
          input.dispatchEvent(new Event('input', { bubbles: true }));
          set_caret_pos(input, 0);
        };

        if (!noconvert) result = format_converter(content, 'html', init_plaintext);
        else { init_plaintext(input.value); result = true; }

        if (!result && curr) this.editor.dom.get('_rc_sig').innerHTML = curr;
      }

      return result;
    };

    // replace selection with text snippet (editor.js replace())
    this.replace = function (input) {
      var ed = this.editor;
      if (!input) return false;

      if (ed) {
        ed.getWin().focus();
        var html; var format;
        if (typeof input === 'object' && ('html' in input)) {
          html = input.html; format = 'html';
        } else {
          if (typeof input === 'object') input = input.text || '';
          html = quote_html(input).replace(/\r?\n/g, '<br/>');
          format = 'text';
        }
        ed.selection.setContent(html, { format: format });
      } else {
        var selection = get_input_selection(editorElement);
          var value = editorElement.value;
          var pre = value.substring(0, selection.start);
          var end = value.substring(selection.end, value.length);
        if (typeof input === 'object') input = input.text || '';
        editorElement.value = pre + input + end;
        set_caret_pos(editorElement, selection.start + input.length);
        editorElement.focus();
      }
    };

    // fill the editor with content (editor.js set_content())
    this.set_content = function (content) {
      if (this.editor) { this.editor.setContent(content); this.editor.getWin().focus(); }
      else { editorElement.value = content; editorElement.focus(); }
    };

    // start/stop spellchecker (editor.js spellcheck_start/stop)
    this.spellcheck_start = function () {
      if (this.editor) {
        tinymce.execCommand('mceSpellCheck', true);
        this.spellcheck_observer();
      } else if (this.spellchecker) {
        // plain mode: GoogieSpell (app.js spellcheck_start)
        this.spellchecker.spellCheck();
        this.spellcheck_observer();
      }
    };

    this.spellcheck_stop = function () {
      var ed = this.editor;
      if (ed) {
        if (ed.spellchecker) {
          ed.spellchecker.suggestions = [];
          ed.spellchecker.markErrors(false);
        }
        if (ed.plugins && ed.plugins.spellchecker) ed.plugins.spellchecker.active = false;
      } else if (ed = this.spellchecker) {
        // app.js spellcheck_stop: while the googie layer is up, "Spell"
        // re-triggers spellCheck() (it resumes editing first)
        if (ed.state && ed.state !== 'ready' && ed.state !== 'no_error_found') {
          ed.spellCheck();
        }
      }
      this.spellcheck_active = false;
      this.spellcheck_observer();
    };

    // app.js: editor.spellcheck_state()
    this.spellcheck_state = function () {
      if (this.editor) return !!this.spellcheck_active;
      var g = this.spellchecker;
      return !!(g && g.state && g.state !== 'ready' && g.state !== 'no_error_found');
    };

    this.get_language = function () {
      return this.editor ? this.editor.settings.spellchecker_language : env.spell_lang;
    };

    this.set_language = function (lang) {
      env.spell_lang = lang;
      if (this.editor) this.editor.settings.spellchecker_language = lang;
    };

    // change user signature (editor.js change_signature) — show_sig=true
    // (re)inserts the given identity's signature
    this.change_signature = function (identity_id, show_sig) {
      var position_element; var cursor_pos; var p = -1;
        var input_message = editorElement;
        var message = input_message.value;
        var sig = env.identity;

      if (!this.editor) { // plain text mode
        if (show_sig && sig && env.signatures && env.signatures[sig]) {
          sig = env.signatures[sig].text.replace(/\r\n/g, '\n');
          p = env.top_posting ? message.indexOf(sig) : message.lastIndexOf(sig);
          if (p >= 0) message = message.substring(0, p) + message.substring(p + sig.length);
        }

        if (show_sig && env.signatures && env.signatures[identity_id]) {
          sig = env.signatures[identity_id].text.replace(/\r\n/g, '\n');
          if (p >= 0) { // in place of removed signature
            message = message.substring(0, p) + sig + message.substring(p);
            cursor_pos = p - 1;
          } else if (!message || !env.compose_mode) {
            cursor_pos = message.length;
            message += '\n\n' + sig;
          } else if (env.top_posting && !env.sig_below) {
            var pos = 0;
            try { pos = input_message.selectionStart; } catch (e) { /* */ }
            if (pos) {
              message = message.substring(0, pos) + '\n' + sig + '\n\n' + message.substring(pos);
              cursor_pos = pos;
            } else {
              message = '\n\n' + sig + '\n\n' + message.replace(/^[\r\n]+/, '');
              cursor_pos = 0;
            }
          } else {
            message = message.replace(/[\r\n]+$/, '');
            cursor_pos = !env.top_posting && message.length ? message.length + 1 : 0;
            message += '\n\n' + sig;
          }
        } else {
          cursor_pos = env.top_posting ? 0 : message.length;
        }

        input_message.value = message;
        set_caret_pos(input_message, cursor_pos);
      } else if (show_sig && env.signatures) { // html
        var sigElem = this.editor.dom.get('_rc_sig');
        if (!sigElem) {
          var body = this.editor.getBody();
          sigElem = document.createElement('div');
          sigElem.id = '_rc_sig';
          if (env.top_posting && !env.sig_below && env.compose_mode
            && (body.childNodes.length > 1 || body.textContent)) {
            this.editor.getWin().focus();
            var node = this.editor.selection.getNode();
            var anchor = node.nodeName === 'BODY' ? body.firstChild : node.nextSibling;
            var br_p = document.createElement('p');
            br_p.appendChild(document.createElement('br'));
            body.insertBefore(br_p, anchor);
            body.insertBefore(sigElem, br_p);
          } else {
            body.appendChild(sigElem);
            position_element = env.top_posting && env.compose_mode ? body.firstChild : sigElem.previousElementSibling;
          }
        }
        sigElem.innerHTML = env.signatures[id] ? env.signatures[id].html : '';
      } else if (!env.top_posting) {
        position_element = this.editor.getBody().lastElementChild;
      }

      if (this.editor && position_element) {
        this.editor.selection.select(position_element, true);
      }
    };

    // trigger content save (editor.js save)
    this.save = function () {
      if (this.editor) this.editor.save();
    };
  }

  // ------------------------------------------------------------- ui.js side
  // html_editor_init(obj): the strip button + autoresize + control binding
  function html_editor_init(obj) {
    var editor = obj;
      var parent = editor.parentNode;
      var readonly = editor.hasAttribute('readonly') || editor.disabled;
      var plain_btn = document.createElement('a');
    plain_btn.className = 'mce-i-html';
    plain_btn.href = '#';
    plain_btn.tabIndex = readonly ? -1 : 0;
    plain_btn.title = get_label('htmltoggle');
    if (readonly) plain_btn.setAttribute('disabled', 'disabled');

    var toolbar = document.createElement('div');
    toolbar.className = 'editor-toolbar';
    toolbar.appendChild(plain_btn);

    var is_table = parent.tagName.toLowerCase() === 'td';
      var sw;
    if (is_table) {
      // the switch control is the checkbox/hidden input in the next row
      var row = parent.parentNode.nextElementSibling;
      sw = row && row.querySelector('input');
    } else {
      sw = editor.nextElementSibling;
      if (sw && !(sw.tagName === 'SELECT' && sw.classList.contains('hidden'))) sw = null;
    }

    textarea_autoresize_init(editor);
    if (!sw) return;

    parent.classList.add('html-editor');

    plain_btn.addEventListener('click', function (e) {
      e.preventDefault();
      if (!readonly && cc_toggle_editor({ id: editor.id, html: true })) {
        parent.classList.add('ishtml');
      }
    });
    plain_btn.addEventListener('keydown', function (e) {
      if (e.which === 9) { editor.focus(); e.preventDefault(); }
    });

    editor.parentNode.insertBefore(toolbar, editor.nextSibling);
    editor._ccControl = sw;
    editor.addEventListener('keydown', function (e) {
      if (e.altKey && e.which === 121) plain_btn.focus();
    });

    if (is_table) {
      sw.parentNode.parentNode.style.display = 'none';
      if (parent.previousElementSibling) parent.previousElementSibling.style.display = 'none';
      parent.classList.add('col-sm-12');
    }
  }

  // ----------------------------------------------------------- command side
  // rcmail.command('toggle-editor', {id, html, noconvert}) — app.js:5029 +
  // rcmail.editor_init(null, id) (app.js:8913). The command creates the
  // editor object on demand for the compose body (first toggle).
  var editors = {};

  function get_editor(id, mode) {
    if (!editors[id]) {
      var cfg = env.editor_config || {};
      if (mode) cfg = Object.assign({}, cfg, { mode: mode });
      editors[id] = new rcube_text_editor(cfg, id);
    }
    return editors[id];
  }

  function cc_toggle_editor(props) {
    var ed = get_editor(props.id || env.composebody);
    // reference: this.editor.toggle(props.html, props.noconvert || false)
    var result = ed.toggle(props.html, props.noconvert || false);
      var control = byId(ed.id)._ccControl;
      var mode;

    mode = result ? (props.html ? 'html' : 'plain') : (props.html ? 'plain' : 'html');

    // update internal format flag(s)
    var isHtml = document.querySelector("[name='_is_html']");
    if (isHtml) isHtml.value = mode === 'html' ? 1 : 0;
    var fmt = document.getElementById('composeformat');
    if (fmt) fmt.value = mode;

    if (control) {
      if (control.type === 'checkbox') control.checked = mode === 'html';
      else control.value = mode;
    }
    return result;
  }

  // rcmail.command('change_identity', select) — app.js change_identity():
  // updates identity/reply-to/bcc fields and (re)inserts the signature
  function cc_change_identity(elem, show) {
    if (!elem || !elem.options) return false;
    var id = elem.value;
      var got_sig = !!(env.signatures && env.signatures[id]);
      var old_id = env.identity;
      var show_sig = show ? show : env.show_sig;

    // reference enables the Signature toolbar button iff a signature exists
    var btn = byId('tb-signature');
    if (btn) {
      btn.classList.toggle('disabled', !got_sig);
      btn.toggleAttribute('aria-disabled', !got_sig);
      btn.tabIndex = got_sig ? 2 : -1;
    }

    // update reply-to/bcc fields with addresses defined in identities
    ['replyto', 'bcc'].forEach(function (key) {
      var rx;
        var old_val = old_id && env.identities[old_id] ? env.identities[old_id][key] : '';
        var new_val = id && env.identities[id] ? env.identities[id][key] : '';
        var input = document.querySelector("[name='_" + (key === 'replyto' ? 'reply_to' : key) + "']");
      if (!input) return;
      var input_val = input.value;
      if (old_val && input_val) {
        rx = new RegExp('\\s*' + old_val.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*');
        input_val = input_val.replace(rx, '');
      }
      input_val = String(input_val).replace(/[,;]\s*[,;]/g, ',').replace(/^[\s,;]+/, '');
      if (new_val && input_val.indexOf(new_val) === -1 && input_val.indexOf(new_val.replace(/"/g, '')) === -1) {
        if (input_val) input_val = input_val.replace(/[,;\s]+$/, '') + ', ';
        input_val += new_val + ', ';
      }
      if (old_val || new_val) input.value = input_val;
    });

    var ed = editors[env.composebody];
    if (ed) ed.change_signature(id, show_sig);

    env.identity = id;
    return true;
  }

  // rcmail.command() subset for the compose toolbar
  function cc_command(cmd, props) {
    var ed = editors[env.composebody];
    if (cmd === 'toggle-editor') {
      // elastic strip toggle (ui.js): props = {id, html}
      return cc_toggle_editor(props || {});
    }
    if (cmd === 'spellcheck') {
      if (ed && ed.is_html()) {
        if (ed.spellcheck_state()) ed.spellcheck_stop();
        else ed.spellcheck_start();
        return true;
      }
      if (window.googie) {
        // plain mode: app.js uses editor.spellchecker (GoogieSpell);
        // start() and stop() both end in spellCheck() while layer toggles
        window.googie.spellCheck();
        return true;
      }
      return false; // no googie loaded: the page keeps native spellcheck
    }
    if (cmd === 'insert-sig') {
      return cc_change_identity(byId('identities'), true);
    }
    if (cmd === 'insert-response') {
      if (ed) ed.replace(props || {});
      return true;
    }
    return false;
  }

  // public API used by the templates
  window.cc_editor = {
    env: env,
    init_page: function (pageEnv) {
      Object.assign(env, pageEnv || {});
      document.querySelectorAll('textarea[data-html-editor]').forEach(html_editor_init);
    },
    // eager init for identity/response pages (server emits editor_init there)
    init_editor: function (id, mode) { get_editor(id, mode); },
    toggle: cc_toggle_editor,
    command: cc_command,
    change_identity: cc_change_identity,
    get: get_editor,
    get_editor_for: function (id) { return editors[id] || null; }
  };
})(window, document);
