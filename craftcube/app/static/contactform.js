/* Contact edit form behaviors — port of Roundcube 1.7.5 rcube_webmail
 * (program/js/app.js): init_contact_form / init_edit_field /
 * insert_edit_field / delete_edit_field. The elastic contact form keeps
 * the authoritative column metadata server-side (rcube_action_contacts_index
 * ::$CONTACT_COLTYPES exported as rcmail.env.coltypes); here the same
 * subset lives in COLTYPES. Rows built client-side mirror the
 * 'compact' DOM the reference produces (row.input-group,
 * .input-group-prepend/.input-group-append, input.form-control).
 */
(function () {
  'use strict';

  // subset of rcube_action_contacts_index::$CONTACT_COLTYPES relevant to
  // the add-field menu; visible=1 rows clear instead of being removed
  var COLTYPES = {
    email:      { label: 'Email',        type: 'text',      visible: true },
    phone:      { label: 'Phone',        type: 'text',      visible: true },
    address:    { label: 'Address',      type: 'composite', visible: true },
    website:    { label: 'Website',      type: 'text' },
    im:         { label: 'IM',           type: 'text' },
    gender:     { label: 'Gender',       type: 'select',    visible: true, limit: 1 },
    birthday:   { label: 'Birthday',     type: 'text',      visible: true, limit: 1 },
    notes:      { label: 'Notes',        type: 'textarea',  visible: true, limit: 1 },
    maidenname: { label: 'Maiden Name',  type: 'text',      limit: 1 },
    anniversary:{ label: 'Anniversary',  type: 'text',      limit: 1 },
    manager:    { label: 'Manager',      type: 'text',      limit: 1 },
    assistant:  { label: 'Assistant',    type: 'text',      limit: 1 },
    spouse:     { label: 'Spouse',       type: 'text',      limit: 1 }
  };
  // rcube init_edit_field(): placeholder = column label when the input has
  // no <label for="ff_COL"> (child columns included, like the reference)
  var PLACEHOLDERS = {
    email: 'Email', phone: 'Phone', website: 'Website', im: 'IM',
    street: 'Street', locality: 'City', zipcode: 'ZIP Code',
    region: 'State/Province', country: 'Country'
  };

  var counts = {};

  function tpl(name) {
    var t = document.getElementById('cc-tpl-' + name);
    return t && t.content ? t.content.cloneNode(true) : null;
  }

  function section(name) {
    return document.getElementById('contactsection' + name);
  }

  function countOf(col) {
    if (!(col in counts)) {
      counts[col] = document.querySelectorAll('.ff_' + col).length;
    }
    return counts[col];
  }

  function setPlaceholder(node, col) {
    var ph = PLACEHOLDERS[col];
    if (ph && !document.querySelector('label[for="ff_' + col + '"]')) {
      node.setAttribute('placeholder', ph);
    }
  }

  // app.js init_contact_form(): placeholders on every rendered col
  function initEditFields() {
    Object.keys(PLACEHOLDERS).forEach(function (col) {
      document.querySelectorAll('.ff_' + col).forEach(function (el) {
        setPlaceholder(el, col);
      });
    });
  }

  // app.js insert_edit_field()
  function insertEditField(col, menu) {
    var sectionName = menu.getAttribute('rel');
    var elem = document.getElementById('ff_' + col);

    if (elem) {
      // head columns ("just make pre-defined input field visible"): the
      // server renders the empty row hidden and lists it in the menu
      var lab = document.querySelector('label[for="ff_' + col + '"]');
      if (lab && lab.parentElement) lab.parentElement.style.display = '';
      elem.style.display = '';
      elem.focus();
      setOptionDisabled(menu, col, true);
      return;
    }

    var sec = section(sectionName);
    if (!sec) return;

    var container = sec.querySelector('.contactcontroller' + col);
    var created = false;
    if (!container) {
      container = document.createElement('fieldset');
      container.className = 'contactfieldgroup contactcontroller' + col;
      var groups = sec.querySelectorAll('.contactfieldgroup');
      if (groups.length) {
        groups[groups.length - 1].after(container);
      } else {
        sec.prepend(container);
      }
      created = true;
    }

    var frag = tpl(col);
    if (!frag) return;
    var fsRoot = frag.firstElementChild &&
                 frag.firstElementChild.tagName === 'FIELDSET'
                 ? frag.firstElementChild : null;
    var row = fsRoot ? fsRoot.querySelector('.row') : frag.querySelector('.row');

    var idSeq = countOf(col);
    frag.querySelectorAll('[id]').forEach(function (el) {
      el.id = el.id.replace(/0$/, String(idSeq));
    });
    frag.querySelectorAll('label[for]').forEach(function (el) {
      el.htmlFor = el.htmlFor.replace(/0$/, String(idSeq));
    });

    if (created && fsRoot) {
      // the template fieldset replaces the bare one we just made
      container.replaceWith(fsRoot);
      container = fsRoot;
    } else if (row) {
      container.appendChild(row);
    } else {
      container.appendChild(frag);
    }
    container.style.display = '';
    counts[col] = idSeq + 1;

    // main input gets the ff_<col><n> id like the reference
    var main = container.querySelector('input.ff_' + col + ', textarea.ff_' + col +
                                       ', select.ff_' + col);
    if (main && !main.id) main.id = 'ff_' + col + idSeq;

    // placeholder + focus like the reference
    container.querySelectorAll('.ff_street,.ff_locality,.ff_zipcode,.ff_region,.ff_country')
      .forEach(function (el) {
        ['street', 'locality', 'zipcode', 'region', 'country'].forEach(function (c) {
          if (el.classList.contains('ff_' + c)) setPlaceholder(el, c);
        });
      });
    if (main) {
      setPlaceholder(main, col);
      if (main.tagName !== 'SELECT') main.focus();
    }

    var prop = COLTYPES[col];
    if (prop && prop.limit && counts[col] >= prop.limit) {
      setOptionDisabled(menu, col, true);
    }
  }

  function setOptionDisabled(menu, col, disabled) {
    var opt = menu.querySelector('option[value="' + col + '"]');
    if (opt) opt.disabled = disabled;
  }

  // app.js delete_edit_field()
  function deleteEditField(btn) {
    var col = btn.getAttribute('rel'),
        prop = COLTYPES[col] || {},
        row = btn.closest('div.row'),
        fieldset = btn.closest('fieldset.contactfieldgroup'),
        menu = fieldset && fieldset.parentElement
               ? fieldset.parentElement.querySelector('select.addfieldmenu') : null;

    if ((--counts[col] <= 0) && prop.visible) {
      // "just clear input but don't hide the last field" (selects included)
      row.querySelectorAll('input').forEach(function (i) { i.value = ''; });
      counts[col] = 0;
    } else {
      row.remove();
      if (!fieldset.querySelector('div.row')) fieldset.style.display = 'none';
    }

    if (menu) {
      var opt = menu.querySelector('option[value="' + col + '"]');
      if (opt) {
        opt.disabled = false;
      } else {
        opt = document.createElement('option');
        opt.value = col;
        opt.textContent = prop.label || col;
        menu.appendChild(opt);
      }
      menu.style.display = '';
    }
  }

  document.addEventListener('change', function (e) {
    var sel = e.target.closest && e.target.closest('select.addfieldmenu');
    if (!sel || !sel.value) return;
    insertEditField(sel.value, sel);
    sel.value = '';
  });

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('a.contactfieldbutton.deletebutton');
    if (!btn) return;
    e.preventDefault();
    deleteEditField(btn);
  });

  // show page: group membership checkboxes (program/js/app.js
  // group_member_change -> group-addmembers/group-delmembers XHR)
  document.addEventListener('change', function (e) {
    var cb = e.target.closest && e.target.closest('input.groupmember');
    if (!cb) return;
    var form = cb.closest('form');
    var cid = form && form.querySelector('input[name=_cid]');
    if (!cid) return;
    var url = '/contacts/group-' + (cb.checked ? 'add' : 'del') + 'members';
    var body = new URLSearchParams({ _cid: cid.value, _gid: cb.value, _source: '0' });
    fetch(url, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest',
                 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString()
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.label && window.cc_display) cc_display(j.label, 'confirmation');
      var li = cb.closest('li');
      if (li && j && j.exec && j.exec[0]) {
        var count = li.querySelector('.count');
        if (count) count.textContent = j.exec[0].count;
      }
    });
  });

  window.cc_contact = {
    delete_photo: function () {
      // rcube_contact_photo delete: set the '-del-' marker, show placeholder
      var h = document.getElementById('ff_photo');
      if (h) h.value = '-del-';
      var pic = document.querySelector('#contactpic img');
      if (pic) {
        var ph = pic.getAttribute('data-placeholder');
        if (ph) pic.src = ph;
        pic.style.visibility = 'hidden';
      }
      var btn = document.querySelector('.contactphoto-delete');
      if (btn && btn.parentNode) btn.parentNode.removeChild(btn);
    }
  };

  document.addEventListener('DOMContentLoaded', initEditFields);
  initEditFields();
})();
