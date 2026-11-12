/*
 * GoogieSpell port for the plain-text compose editor (server-side spell
 * checking with a decorated edit layer), mirroring
 * program/js/googiespell.js as loaded by the reference compose page
 * (program/actions/mail/compose.php: new GoogieSpell(img, url+'&lang=',
 * dictionary); setDecoration(false); decorateTextarea(composebody)).
 *
 * The reference build depends on jQuery and rcmail; this port is plain
 * DOM + XMLHttpRequest and routes the couple of user-visible messages
 * through the shared cc_display/cc_get_label helpers. Behaviour, DOM
 * classes (.googie_edit_layer/.googie_link/.googie_window/.googie_list)
 * and the Googie XML protocol are kept 1:1.
 *
 * @license GPL-3.0-or-later (original GoogieSpell: GPL-2.0+, Roundcube
 * Dev Team; @author 4mir Salihefendic, Aleksander Machniak)
 */

var GOOGIE_CUR_LANG,
    GOOGIE_DEFAULT_LANG = 'en';

function GoogieSpell(img_dir, server_url, has_dict) {
    var ref = this;

    GOOGIE_CUR_LANG = GOOGIE_DEFAULT_LANG;

    this.array_keys = function (arr) {
        var res = [];
        for (var key in arr) res.push([key]);
        return res;
    };

    this.img_dir = img_dir;
    this.server_url = server_url;
    this.has_dictionary = !!has_dict;

    this.org_lang_to_word = { en: 'English' };
    this.lang_to_word = this.org_lang_to_word;
    this.langlist_codes = this.array_keys(this.lang_to_word);
    this.show_change_lang_pic = false; // roundcube mod.
    this.report_state_change = true;

    this.ta_scroll_top = 0;
    this.el_scroll_top = 0;

    this.lang_chck_spell = 'Check spelling';
    this.lang_revert = 'Revert to';
    this.lang_close = 'Close';
    this.lang_rsm_edt = 'Resume editing';
    this.lang_no_error_found = 'No spelling errors found';
    this.lang_no_suggestions = 'No suggestions';
    this.lang_learn_word = 'Add to dictionary';

    this.use_ok_pic = false; // added by roundcube
    this.show_spell_img = false; // roundcube mod.
    this.decoration = true;
    this.use_close_btn = false;
    this.edit_layer_dbl_click = true;
    this.main_controller = true;
    this.use_focus = false;
    this.ignore = false;

    this.state = null;
    this.spelling_state_observer = null;
    this.all_errors_fixed_observer = null;
    this.show_menu_observer = null;
    this.custom_item_evaluator = null;
    this.custom_spellcheck_starter = null;
    this.custom_no_spelling_error = null;
    this.custom_ajax_error = null;
    this.extra_menu_items = [];

    this.results = [];
    this.error_links = [];
    this.original_text = '';

    // ------------------------------------------------------ DOM helpers
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    this.setStateChanged = function (current_state) {
        this.state = current_state;
        if (this.spelling_state_observer != null && this.report_state_change) {
            this.spelling_state_observer(current_state, this);
        }
    };

    this.setReportStateChange = function (bool) { this.report_state_change = bool; };

    this.getUrl = function () { return this.server_url + GOOGIE_CUR_LANG; };

    this.escapeSpecial = function (val) {
        return val ? val.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
    };

    this.createXMLReq = function (text) {
        return '<?xml version="1.0" encoding="utf-8" ?>'
            + '<spellrequest textalreadyclipped="0" ignoredups="0" ignoredigits="1" ignoreallcaps="1">'
            + '<text>' + text + '</text></spellrequest>';
    };

    this.post = function (body, on_success, on_error) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', ref.getUrl(), true);
        xhr.setRequestHeader('Content-Type', 'text/xml');
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== 4) return;
            if (xhr.status >= 200 && xhr.status < 300) on_success(xhr.responseText);
            else on_error(xhr);
        };
        xhr.send(body);
    };

    this.serverError = function () {
        // googiespell: rcmail.alert_dialog('An error was encountered...')
        if (ref.custom_ajax_error) {
            ref.custom_ajax_error(ref);
        } else if (window.cc_display) {
            window.cc_display('An error was encountered on the server. Please try again later.', 'error');
        }
        if (ref.main_controller && ref.spell_span) ref.spell_span.parentNode && ref.spell_span.parentNode.removeChild(ref.spell_span);
        ref.removeIndicator();
        ref.checkSpellingState();
    };

    this.spellCheck = function (ignore) {
        this.prepare(ignore);
        if (!this.text_area) return;
        if (this.ignore) return; // prepare() aborted (empty text)
        var orig_text = this.escapeSpecial(this.original_text);
        this.post(this.createXMLReq(orig_text), function (data) {
            ref.processData(data);
            if (!ref.results.length) {
                if (!ref.custom_no_spelling_error) ref.flashNoSpellingErrorState();
                else ref.custom_no_spelling_error(ref);
            }
            ref.removeIndicator();
        }, function () {
            ref.serverError();
        });
    };

    this.learnWord = function (word) {
        var esc = this.escapeSpecial(word.innerHTML);
        this.post('<?xml version="1.0" encoding="utf-8" ?><learnword><text>'
            + esc + '</text></learnword>', function () {}, function () {});
    };

    this.prepare = function (ignore) {
        this.cnt_errors_fixed = 0;
        this.cnt_errors = 0;
        this.setStateChanged('checking_spell');
        this.original_text = '';

        if (this.main_controller) this.appendIndicator();

        this.error_links = [];
        this.ta_scroll_top = this.text_area.scrollTop;
        this.ignore = false;

        if (this.text_area.value === '' || ignore) {
            if (!this.custom_no_spelling_error) this.flashNoSpellingErrorState();
            else this.custom_no_spelling_error(this);
            this.removeIndicator();
            this.ignore = true; // abort: nothing to check
            return;
        }

        var cs = window.getComputedStyle(this.text_area);
        var width = this.text_area.clientWidth;
        var height = cs.boxSizing === 'border-box'
            ? this.text_area.offsetHeight : this.text_area.clientHeight;

        this.createEditLayer(width, height);
        this.createErrorWindow();

        document.body.appendChild(this.error_window);

        this.original_text = this.text_area.value;
    };

    this.parseResult = function (r_text) {
        // reference parser: pull <c ...>suggestions</c> entries verbatim
        var re_split_attr_c = /\w+="(\d+|true)"/g,
            re_split_text = /\t/g,
            matched_c = r_text.match(/<c[^>]*>[^<]*<\/c>/g),
            results = [];

        if (matched_c == null) return results;

        for (var i = 0, len = matched_c.length; i < len; i++) {
            var item = [];
            this.errorFound();

            item.attrs = [];
            var c_attr, val,
                split_c = matched_c[i].match(re_split_attr_c);
            if (!split_c) continue;
            for (var j = 0; j < split_c.length; j++) {
                c_attr = split_c[j].split(/=/);
                val = c_attr[1].replace(/"/g, '');
                item.attrs[c_attr[0]] = val !== 'true' ? parseInt(val, 10) : val;
            }

            item.suggestions = [];
            var only_text = matched_c[i].replace(/<[^>]*>/g, ''),
                split_t = only_text.split(re_split_text);
            for (var k = 0; k < split_t.length; k++) {
                if (split_t[k] !== '') item.suggestions.push(split_t[k]);
            }
            results.push(item);
        }
        return results;
    };

    this.processData = function (data) {
        this.results = this.parseResult(data);
        if (this.results.length) {
            this.showErrorsInIframe();
            this.resumeEditingState();
        }
    };

    // ------------------------------------------------------ error window
    this.createErrorWindow = function () {
        this.error_window = el('div', 'googie_window popupmenu');
        this.error_window.setAttribute('googie_action_btn', '1');
        this.error_window.style.display = 'none';
    };

    this.isErrorWindowShown = function () {
        return this.error_window && this.error_window.style.display !== 'none';
    };

    this.hideErrorWindow = function () {
        if (this.error_window) this.error_window.style.display = 'none';
    };

    this.updateOriginalText = function (offset, old_value, new_value, id) {
        var part_1 = this.original_text.substring(0, offset),
            part_2 = this.original_text.substring(offset + old_value.length),
            add_2_offset = new_value.length - old_value.length;

        this.original_text = part_1 + new_value + part_2;
        this.text_area.value = this.original_text;
        for (var j = 0, len = this.results.length; j < len; j++) {
            // Don't edit the offset of the current item
            if (j !== id && j > id) this.results[j].attrs.o += add_2_offset;
        }
    };

    this.saveOldValue = function (elm, old_value) {
        elm.is_changed = true;
        elm.old_value = old_value;
    };

    this.correctError = function (id, elm, l_elm) {
        var old_value = elm.innerHTML,
            new_value = l_elm.nodeType === 3 ? l_elm.nodeValue : l_elm.innerHTML,
            offset = this.results[id].attrs.o;

        this.hideErrorWindow();
        this.updateOriginalText(offset, old_value, new_value, id);

        elm.innerHTML = new_value;
        elm.style.color = 'green';
        elm.setAttribute('is_corrected', 'true');

        this.results[id].attrs.l = new_value.length;

        if (!this.isDefined(elm.old_value)) this.saveOldValue(elm, old_value);

        this.errorFixed();
    };

    this.ignoreError = function (elm) {
        elm.removeAttribute('class');
        elm.style.color = '';
        elm.onclick = null;
        this.hideErrorWindow();
    };

    this.item_onmouseover = function () {
        if (this.className !== 'googie_list_revert' && this.className !== 'googie_list_close') {
            this.className = 'googie_list_onhover';
        } else {
            this.parentNode.className = 'googie_list_onhover';
        }
    };

    this.item_onmouseout = function () {
        if (this.className !== 'googie_list_revert' && this.className !== 'googie_list_close') {
            this.className = 'googie_list_onout';
        } else {
            this.parentNode.className = 'googie_list_onout';
        }
    };

    this.showErrorWindow = function (elm, id) {
        if (this.show_menu_observer) this.show_menu_observer(this);

        var r = elm.getBoundingClientRect(),
            pos = { top: r.top + window.scrollY, left: r.left + window.scrollX },
            list = el('ul', 'googie_list toolbarmenu');
        list.setAttribute('googie_action_btn', '1');

        this.error_window.innerHTML = '';

        // [Add to dictionary] button (needs a writable dictionary)
        if (this.has_dictionary && elm.getAttribute('is_corrected') !== 'true') {
            var li_learn = el('li');
            li_learn.setAttribute('googie_action_btn', '1');
            li_learn.style.cursor = 'default';
            li_learn.appendChild(el('a', 'googie_add_to_dict active', this.lang_learn_word));
            li_learn.addEventListener('mouseover', this.item_onmouseover);
            li_learn.addEventListener('mouseout', this.item_onmouseout);
            li_learn.addEventListener('click', function (e) {
                ref.learnWord(elm, id);
                ref.ignoreError(elm, id);
            });
            list.appendChild(li_learn);
        }

        var suggestions = this.results[id].suggestions,
            offset = this.results[id].attrs.o;

        for (var i = 0; i < suggestions.length; i++) {
            var li = el('li'),
                a = el('a', 'active', suggestions[i]);
            li.addEventListener('mouseover', this.item_onmouseover);
            li.addEventListener('mouseout', this.item_onmouseout);
            li.setAttribute('googie_action_btn', '1');
            (function (sug) {
                li.addEventListener('click', function (e) {
                    ref.correctError(id, elm, e.target.firstChild || { nodeType: 3, nodeValue: sug });
                });
            })(suggestions[i]);
            li.appendChild(a);
            list.appendChild(li);
        }

        // The element is changed, append the revert
        if (elm.is_changed && elm.innerHTML !== elm.old_value) {
            var old_value = elm.old_value,
                li_rev = el('li'),
                a_rev = el('a', 'googie_list_revert active', this.lang_revert + ' ' + old_value);
            li_rev.setAttribute('googie_action_btn', '1');
            li_rev.addEventListener('mouseover', this.item_onmouseover);
            li_rev.addEventListener('mouseout', this.item_onmouseout);
            li_rev.addEventListener('click', function () {
                ref.updateOriginalText(offset, elm.innerHTML, old_value, id);
                elm.removeAttribute('is_corrected');
                elm.style.color = '#b91414';
                elm.innerHTML = old_value;
                ref.hideErrorWindow();
            });
            li_rev.appendChild(a_rev);
            list.appendChild(li_rev);
        }

        // Append the edit box
        var edit_row = el('li'),
            edit_input = el('input'),
            ok_pic = el('button', 'mainaction save googie_ok_button btn-sm', 'OK'),
            edit_form = el('form');

        edit_input.style.width = '120px';
        edit_input.value = elm.textContent;
        edit_input.setAttribute('googie_action_btn', '1');
        edit_row.style.cursor = 'default';
        edit_row.setAttribute('googie_action_btn', '1');
        edit_row.addEventListener('click', function () { return false; });
        edit_form.setAttribute('googie_action_btn', '1');
        edit_form.style.cursor = 'default';
        edit_form.style.whiteSpace = 'nowrap';

        function onsub(ev) {
            ev.preventDefault();
            if (edit_input.value !== '') {
                if (!ref.isDefined(elm.old_value)) ref.saveOldValue(elm, elm.innerHTML);
                ref.updateOriginalText(offset, elm.innerHTML, edit_input.value, id);
                elm.setAttribute('is_corrected', 'true');
                elm.style.color = 'green';
                elm.textContent = edit_input.value;
                ref.hideErrorWindow();
            }
            return false;
        }
        edit_form.addEventListener('submit', onsub);
        ok_pic.addEventListener('click', onsub);
        edit_form.appendChild(edit_input);
        edit_form.appendChild(ok_pic);
        edit_row.appendChild(edit_form);
        list.appendChild(edit_row);

        this.error_window.appendChild(list);

        // rcmail.triggerEvent('googiespell_create', ...)
        document.dispatchEvent(new CustomEvent('googiespell_create', { detail: { obj: this.error_window } }));

        // calculate and set position (googiespell uses offset + page height)
        // elastic renders the window as a popover (ui.js googiespell_create
        // hook); .popupmenu is display:none on desktop unless explicitly shown
        this.error_window.classList.add('popover');
        this.error_window.style.display = 'block';
        var height = this.error_window.offsetHeight,
            width = this.error_window.offsetWidth,
            pageheight = document.documentElement.scrollHeight,
            pagewidth = document.documentElement.scrollWidth,
            top = pos.top + height + 20 < pageheight ? pos.top + 20 : pos.top - height,
            left = pos.left + width < pagewidth ? pos.left : pos.left - width;

        if (left < 0) left = 0;
        if (top < 0) top = 0;
        this.error_window.style.cssText += ';top:' + top + 'px;left:' + left + 'px;position:absolute;';
    };

    // ------------------------------------------------------ edit layer
    this.createEditLayer = function (width, height) {
        this.edit_layer = el('div', 'googie_edit_layer');
        this.edit_layer.id = 'googie_edit_layer';
        this.edit_layer.style.width = width + 'px';
        this.edit_layer.style.height = height + 'px';
        this.edit_layer.style.overflow = 'auto';

        if (this.edit_layer_dbl_click) {
            this.edit_layer.addEventListener('dblclick', function (e) {
                if (!e.target.classList.contains('googie_link') && !ref.isErrorWindowShown()) {
                    ref.resumeEditing();
                    setTimeout(function () { ref.text_area.focus(); }, 10);
                }
                return false;
            });
        }
    };

    this.resumeEditing = function () {
        this.setStateChanged('ready');

        if (this.edit_layer) this.el_scroll_top = this.edit_layer.scrollTop;

        this.hideErrorWindow();

        if (!this.ignore) {
            if (this.edit_layer && this.edit_layer.parentNode) {
                this.edit_layer.parentNode.removeChild(this.edit_layer);
            }
            this.text_area.style.display = '';

            if (this.el_scroll_top !== undefined) {
                this.text_area.scrollTop = this.el_scroll_top;
            }
        }
        this.checkSpellingState(false);
    };

    this.createErrorLink = function (text, id) {
        var elm = el('span', 'googie_link');
        elm.innerHTML = text;
        elm.setAttribute('googie_action_btn', '1');
        elm.setAttribute('g_id', id);
        elm.addEventListener('click', function (e) {
            e.preventDefault();
            ref.showErrorWindow(elm, id);
        });
        return elm;
    };

    this.createPart = function (txt_part) {
        if (txt_part === ' ') return document.createTextNode(' ');

        txt_part = this.escapeSpecial(txt_part);
        txt_part = txt_part.replace(/\n/g, '<br>');
        txt_part = txt_part.replace(/ {4}/g, ' &nbsp;');
        txt_part = txt_part.replace(/^ /g, '&nbsp;');
        txt_part = txt_part.replace(/ $/g, '&nbsp;');

        var span = el('span');
        span.innerHTML = txt_part;
        return span;
    };

    this.showErrorsInIframe = function () {
        var output = el('div'),
            pointer = 0,
            results = this.results;

        if (results.length > 0) {
            for (var i = 0, length = results.length; i < length; i++) {
                var offset = results[i].attrs.o,
                    len = results[i].attrs.l,
                    part_1_text = this.original_text.substring(pointer, offset),
                    part_1 = this.createPart(part_1_text);

                output.appendChild(part_1);
                pointer += offset - pointer;

                var err_link = this.createErrorLink(this.original_text.substr(offset, len), i);
                this.error_links.push(err_link);
                output.appendChild(err_link);
                pointer += len;
            }

            var part_2_text = this.original_text.substr(pointer, this.original_text.length),
                part_2 = this.createPart(part_2_text);
            output.appendChild(part_2);
        } else {
            output.innerHTML = this.original_text;
        }

        output.style.textAlign = 'left';

        if (this.custom_item_evaluator) {
            var me = this;
            this.error_links.forEach(function (elm) { me.custom_item_evaluator(me, elm); });
        }

        // sync the textarea's font/scroll so the layer sits exactly over
        // the same box (reference sizes through jQuery .width/.height)
        var ta = this.text_area,
            cs = window.getComputedStyle(ta);
        ['fontFamily', 'fontSize', 'lineHeight', 'paddingTop', 'paddingRight',
         'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth',
         'borderBottomWidth', 'borderLeftWidth', 'whiteSpace', 'wordWrap']
            .forEach(function (p) { this.edit_layer.style[p] = cs[p]; }, this);
        this.edit_layer.style.boxSizing = 'border-box';
        this.edit_layer.style.background = cs.backgroundColor;
        this.edit_layer.style.color = cs.color;
        this.edit_layer.style.width = ta.offsetWidth + 'px';
        this.edit_layer.style.height = ta.offsetHeight + 'px';

        this.edit_layer.appendChild(output);

        // Hide text area and show edit layer
        ta.style.display = 'none';
        ta.parentNode.insertBefore(this.edit_layer, ta);
        this.edit_layer.scrollTop = this.ta_scroll_top;
    };

    // ------------------------------------------------------ state UI
    this.flashNoSpellingErrorState = function () {
        this.setStateChanged('no_error_found');
    };

    this.resumeEditingState = function () {
        this.setStateChanged('resume_editing');
        try { this.edit_layer.scrollTop = this.ta_scroll_top; } catch (e) {}
    };

    this.checkSpellingState = function (fire) {
        if (fire) this.setStateChanged('ready');
    };

    this.setSpellContainer = function () { /* no decoration in elastic */ };
    this.setDecoration = function (bool) { this.decoration = bool; };
    this.setLanguages = function (lang_dict) {
        this.lang_to_word = lang_dict;
        this.langlist_codes = this.array_keys(lang_dict);
    };
    this.setCurrentLanguage = function (lan_code) { GOOGIE_CUR_LANG = lan_code; };

    this.decorateTextarea = function (id) {
        this.text_area = typeof id === 'string' ? document.getElementById(id) : id;
        // reference builds a spell_container row only with decoration on;
        // compose.php calls setDecoration(false), so nothing to insert
    };

    // ------------------------------------------------------ misc
    this.isDefined = function (o) { return o !== undefined && o !== null; };

    this.errorFixed = function () {
        this.cnt_errors_fixed++;
        if (this.all_errors_fixed_observer && this.cnt_errors_fixed === this.cnt_errors) {
            this.hideErrorWindow();
            this.all_errors_fixed_observer();
        }
    };

    this.errorFound = function () { this.cnt_errors++; };

    this.removeIndicator = function () {
        if (window.cc_hide_busy) window.cc_hide_busy(this.rc_msg_id);
    };

    this.appendIndicator = function () {
        // reference: rcmail.set_busy(true, 'checking')
        if (window.cc_display) {
            this.rc_msg_id = window.cc_display(
                (window.cc_get_label && cc_get_label('checking')) || 'Checking...',
                'loading', 120000);
        }
    };
}
