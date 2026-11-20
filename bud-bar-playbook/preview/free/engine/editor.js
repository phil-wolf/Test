/* =====================================================================
   On-page edit mode — ONLY on the online preview pages (claude.ai links).
   It is never copied into the SCORM zips.

   People with edit access see an "Edit text" button. Saved edits go to
   this page's shared store and show for everyone viewing the link.
   They are NOT in the SCORM zips until Claude applies them to /content
   (apply_edits.py) and rebuilds.
   ===================================================================== */
(function () {
  'use strict';

  var C = window.COURSE_DATA;
  var edits = window.CourseEdits = {};       // screen key -> saved edit
  var col = null;                            // the "edits" collection
  var editing = false;
  var bar = document.getElementById('edit-toolbar');
  var linkTarget = null, savedRange = null;

  function P() { return window.CoursePlayer; }
  function docId(key) { return (C.id + '__' + key).replace(/[^A-Za-z0-9_-]/g, '_'); }

  /* ---------- Keep only the formatting the course supports ---------- */
  var KEEP = { P: 1, UL: 1, OL: 1, LI: 1, STRONG: 1, EM: 1, A: 1, H2: 1, MARK: 1, DIV: 1, BR: 1,
               TABLE: 1, THEAD: 1, TBODY: 1, TR: 1, TH: 1, TD: 1, SPAN: 1 };
  var DROP = { SCRIPT: 1, STYLE: 1, IFRAME: 1, OBJECT: 1, EMBED: 1, IMG: 1, svg: 1, SVG: 1, FORM: 1, INPUT: 1, BUTTON: 1, TEMPLATE: 1 };
  var CLASSES = { verify: 1, callout: 1, 'table-wrap': 1, 'sr-only': 1 };
  var RENAME = { B: 'STRONG', I: 'EM', H1: 'H2', H3: 'H2', H4: 'H2' };

  function cleanNode(node) {
    Array.prototype.slice.call(node.childNodes).forEach(function (n) {
      if (n.nodeType === 3) return;
      if (n.nodeType !== 1) { n.remove(); return; }
      var tag = n.tagName.toUpperCase();
      if (DROP[tag]) { n.remove(); return; }
      if (RENAME[tag]) {
        var r = document.createElement(RENAME[tag]);
        while (n.firstChild) r.appendChild(n.firstChild);
        n.replaceWith(r); n = r; tag = r.tagName;
      }
      cleanNode(n);
      if (!KEEP[tag] || (tag === 'SPAN' && !n.classList.contains('sr-only'))) {
        while (n.firstChild) n.parentNode.insertBefore(n.firstChild, n);
        n.remove();
        return;
      }
      Array.prototype.slice.call(n.attributes).forEach(function (a) {
        var name = a.name.toLowerCase(), keep = false;
        if (name === 'class') {
          var cls = a.value.split(/\s+/).filter(function (c) { return CLASSES[c]; });
          if (cls.length) { n.setAttribute('class', cls.join(' ')); keep = true; }
        } else if (tag === 'A' && name === 'href') {
          keep = /^(https?:\/\/|#|downloads\/|mailto:)/i.test(a.value.trim());
        } else if (tag === 'TH' && name === 'scope') {
          keep = true;
        }
        if (!keep) n.removeAttribute(a.name);
      });
      if (tag === 'A') {
        if (!n.getAttribute('href')) {
          while (n.firstChild) n.parentNode.insertBefore(n.firstChild, n);
          n.remove();
        } else if (/^https?:/i.test(n.getAttribute('href'))) {
          n.setAttribute('target', '_blank');
          n.setAttribute('rel', 'noopener');
        }
      }
    });
  }
  function clean(html) {
    var t = document.createElement('template');
    t.innerHTML = html;
    cleanNode(t.content);
    return t.innerHTML.replace(/(<br>\s*)+(<\/(p|li|div|h2)>)/g, '$2').trim();
  }

  /* ---------- Badge on edited screens (everyone sees it) ---------- */
  window.addEventListener('course:rendered', function (e) {
    var s = e.detail.screen;
    if (!edits[s.key]) return;
    var h1 = document.getElementById('screen-title');
    var badge = document.createElement('span');
    badge.className = 'edited-badge';
    badge.textContent = 'Edited on this page · not in the SCORM zip yet';
    h1.parentNode.insertBefore(badge, h1);
  });

  /* ---------- Toolbar ---------- */
  function button(label, title, onClick, cls) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = cls || 'tb';
    b.textContent = label;
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });  // keep the text selection
    b.addEventListener('click', onClick);
    return b;
  }
  function sep() { var d = document.createElement('span'); d.className = 'sep'; return d; }
  function cmd(name) { return function () { document.execCommand(name, false, null); }; }

  var status, linkBox, linkInput, revertBtn;
  function buildToolbar() {
    bar.innerHTML = '';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', 'Text editing');
    var b = button('B', 'Bold', cmd('bold')); b.style.fontWeight = '700';
    var i = button('I', 'Italic', cmd('italic')); i.style.fontStyle = 'italic';
    bar.append(b, i,
      button('• List', 'Bulleted list', cmd('insertUnorderedList')),
      button('1. List', 'Numbered list', cmd('insertOrderedList')),
      button('Link', 'Add or change a link', openLink),
      button('Flag', 'Insert a [PHILIP TO VERIFY] flag', insertFlag),
      sep());

    linkBox = document.createElement('span');
    linkBox.className = 'link-box';
    linkBox.hidden = true;
    linkInput = document.createElement('input');
    linkInput.type = 'url';
    linkInput.id = 'edit-link-url';
    linkInput.placeholder = 'https://…';
    linkInput.setAttribute('aria-label', 'Link address (leave empty to remove the link)');
    linkInput.className = 'tb';
    linkInput.style.minWidth = '14rem';
    linkInput.style.fontWeight = '400';
    linkInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); applyLink(); } if (e.key === 'Escape') closeLink(); });
    var apply = document.createElement('button');
    apply.type = 'button'; apply.className = 'tb'; apply.textContent = 'Apply link';
    apply.addEventListener('click', applyLink);
    linkBox.append(linkInput, apply);
    bar.appendChild(linkBox);

    status = document.createElement('span');
    status.className = 'edit-status';
    status.setAttribute('role', 'status');
    var grow = document.createElement('span'); grow.className = 'grow';
    revertBtn = button('Revert to original', 'Remove this screen\'s saved edits', revert, 'btn btn-secondary btn-small');
    bar.append(status, grow, revertBtn,
      button('Cancel', 'Discard changes', function () { stop(false); }, 'btn btn-secondary btn-small'),
      button('Save', 'Save changes', save, 'btn btn-primary btn-small'));
  }

  function openLink() {
    var sel = window.getSelection();
    if (!sel.rangeCount || !editableContains(sel.anchorNode)) { say('Select some text first, or click inside a link.'); return; }
    savedRange = sel.getRangeAt(0).cloneRange();
    var n = sel.anchorNode; linkTarget = null;
    while (n && n !== document.body) { if (n.tagName === 'A') { linkTarget = n; break; } n = n.parentNode; }
    if (!linkTarget && savedRange.collapsed) { say('Select the words to turn into a link.'); return; }
    linkInput.value = linkTarget ? linkTarget.getAttribute('href') : 'https://';
    linkBox.hidden = false;
    linkInput.focus();
    linkInput.select();
  }
  function applyLink() {
    var url = linkInput.value.trim();
    if (url && !/^(https?:\/\/|mailto:)/i.test(url)) { say('Links must start with https:// or http://'); return; }
    if (linkTarget) {
      if (url) linkTarget.setAttribute('href', url);
      else { while (linkTarget.firstChild) linkTarget.parentNode.insertBefore(linkTarget.firstChild, linkTarget); linkTarget.remove(); }
    } else if (savedRange && url) {
      var sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(savedRange);
      document.execCommand('createLink', false, url);
    }
    closeLink();
    say(url ? 'Link set. Remember to Save.' : 'Link removed. Remember to Save.');
  }
  function closeLink() { linkBox.hidden = true; linkTarget = null; savedRange = null; }

  function insertFlag() {
    var sel = window.getSelection();
    if (!sel.rangeCount || !editableContains(sel.anchorNode)) { say('Click in the text where the flag should go.'); return; }
    document.execCommand('insertHTML', false, '&nbsp;<mark class="verify">[PHILIP TO VERIFY]</mark>&nbsp;');
  }
  function say(t) { if (status) status.textContent = t; }

  /* ---------- Edit mode ---------- */
  function editables() {
    var art = document.getElementById('screen');
    return [document.getElementById('screen-title')]
      .concat(Array.prototype.slice.call(art.querySelectorAll('.block:not(.block-locked)')));
  }
  function editableContains(node) {
    return editables().some(function (el) { return el.contains(node); });
  }

  function start() {
    if (editing) return;
    editing = true;
    document.body.classList.add('is-editing');
    P().setLocked(true);
    editables().forEach(function (el) { el.contentEditable = 'true'; el.spellcheck = true; });
    var h1 = document.getElementById('screen-title');
    h1.addEventListener('keydown', noEnter);
    revertBtn.hidden = !edits[P().current().key];
    bar.hidden = false;
    closeLink();
    say('Click any outlined text to change it. Quiz, calculator and tables of data stay as they are.');
    editBtn.textContent = 'Editing…';
    editBtn.disabled = true;
    h1.focus();
  }
  function noEnter(e) { if (e.key === 'Enter') e.preventDefault(); }

  function stop(keepStatus) {
    editing = false;
    document.body.classList.remove('is-editing');
    bar.hidden = true;
    editBtn.textContent = 'Edit text';
    editBtn.disabled = false;
    P().setLocked(false);
    P().rerender();
    if (!keepStatus) say('');
  }

  function save() {
    var s = P().current();
    var blocks = s.blocks.map(function (b, bi) {
      if (b.embed) return null;
      var el = document.querySelector('#screen .block[data-block="' + bi + '"]');
      return el ? clean(el.innerHTML) : b.html;
    });
    var title = clean(document.getElementById('screen-title').innerHTML.replace(/<\/?(p|div|br)[^>]*>/gi, ' ')).trim();
    if (!title) { say('The screen title cannot be empty.'); return; }
    var unchanged = title === clean(s.titleHtml) && blocks.every(function (h, bi) {
      return h === null || h === clean(s.blocks[bi].html);
    });
    var ref = col.doc(docId(s.key));
    say('Saving…');
    var job = unchanged
      ? (edits[s.key] ? ref.delete() : Promise.resolve())
      : ref.set({
          course: C.id, key: s.key, file: s.file, screen: s.screenIndex,
          original_title: s.titleHtml.replace(/<[^>]+>/g, ''),
          title_html: title, blocks: blocks,
          course_version: C.version, updated_at: new Date().toISOString()
        });
    job.then(function () {
      if (unchanged) delete edits[s.key];
      else edits[s.key] = { title_html: title, blocks: blocks };
      stop(true);
      say('');
      showNote(unchanged ? 'No changes to save.' : 'Saved. Everyone with this link now sees the new text. Ask Claude to "apply my edits" to update the SCORM zips.');
    }, function (err) { failed(err); });
  }

  function revert() {
    var s = P().current();
    say('Reverting…');
    col.doc(docId(s.key)).delete().then(function () {
      delete edits[s.key];
      stop(true);
      showNote('Reverted this screen to the original text.');
    }, failed);
  }

  function failed(err) {
    var code = err && err.code;
    if (code === 'invalid_argument' || code === 'not_granted' || code === 'revoked') say('You don\'t have permission to save edits on this page.');
    else if (code === 'quota_exceeded') say('The edit store is full. Ask Claude to apply and clear your edits.');
    else say('Could not save. Check your connection and try again.');
  }

  function showNote(text) {
    var b = document.getElementById('banner');
    b.innerHTML = '';
    var p = document.createElement('p');
    p.textContent = text;
    b.appendChild(p);
    b.hidden = false;
  }

  /* ---------- Connect to the page's shared store ---------- */
  var editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'btn btn-primary btn-small';
  editBtn.textContent = 'Edit text';
  editBtn.addEventListener('click', start);

  function applySnapshot(snap) {
    var before = JSON.stringify(edits[P().current().key] || null);
    Object.keys(edits).forEach(function (k) { delete edits[k]; });
    snap.docs.forEach(function (d) {
      var v = d.data();
      if (!v || v.course !== C.id || typeof v.key !== 'string') return;
      edits[v.key] = {
        title_html: clean(String(v.title_html || '')),
        blocks: Array.isArray(v.blocks) ? v.blocks.map(function (h) { return typeof h === 'string' ? clean(h) : null; }) : []
      };
    });
    if (!editing && JSON.stringify(edits[P().current().key] || null) !== before) P().rerender();
  }

  if (!window.claude || typeof window.claude.use !== 'function') return;   // local file or SCORM: no edit mode
  window.claude.use('db').then(function (db) {
    if (!db) return;
    col = db.collection('edits');
    col.onSnapshot(applySnapshot, function () { /* keep showing the built text */ });
    return window.claude.use('user').then(function (user) {
      return user ? user.canEdit() : false;
    }).then(function (can) {
      if (!can) return;
      buildToolbar();
      document.getElementById('top-actions').insertBefore(editBtn, document.getElementById('menu-btn'));
    });
  }).catch(function () { /* no edit mode */ });
})();
