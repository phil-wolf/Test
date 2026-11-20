/* =====================================================================
   LMS debug panel
   Shown automatically in preview mode (no LMS found). Inside a real LMS
   it stays hidden unless the launch URL includes ?debug=1.
   ===================================================================== */
(function () {
  'use strict';

  window.DebugPanel = {
    start: function () {
      var S = window.SCORM;
      var show = S.isMock || /[?&]debug=1\b/.test(window.location.search);
      if (!show) return;

      var KEYS = ['cmi.core.lesson_status', 'cmi.core.score.raw', 'cmi.core.lesson_location',
                  'cmi.core.exit', 'cmi.core.session_time', 'cmi.suspend_data'];

      var root = document.createElement('section');
      root.className = 'debug';
      root.setAttribute('aria-label', 'LMS debug panel');
      root.innerHTML =
        '<button type="button" class="debug-toggle" aria-expanded="false" aria-controls="debug-body">' +
        '<span class="debug-mode"></span> <span class="debug-summary"></span></button>' +
        '<div class="debug-body" id="debug-body" hidden>' +
        '<p class="debug-note"></p>' +
        '<table class="debug-values"><caption>Current LMS values (read at launch or sent since)</caption><tbody></tbody></table>' +
        '<div class="debug-actions">' +
        '<button type="button" data-act="exit">Simulate exit (LMSFinish)</button>' +
        (S.isMock ? '<button type="button" data-act="reset">Reset preview data</button>' : '') +
        '</div>' +
        '<h2 class="debug-h">Call log (newest first)</h2><ol class="debug-log" reversed></ol>' +
        '</div>';
      document.body.appendChild(root);

      var toggle = root.querySelector('.debug-toggle');
      var body = root.querySelector('.debug-body');
      root.querySelector('.debug-mode').textContent = S.isMock ? 'PREVIEW (mock LMS)' : 'LMS debug';
      root.querySelector('.debug-note').textContent = S.isMock
        ? 'No LMS was found, so a mock LMS is recording what would be sent. Data is saved in this browser so you can test resume by reloading.'
        : 'Connected to a real LMS. These are the calls this course is making.';

      toggle.addEventListener('click', function () {
        var open = body.hidden;
        body.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
      });
      root.addEventListener('click', function (e) {
        var act = e.target.getAttribute && e.target.getAttribute('data-act');
        if (act === 'exit') { window.dispatchEvent(new Event('course:exit')); }
        if (act === 'reset') {
          window.__skipExit = true;
          S.resetPreview();
          window.location.reload();
        }
      });

      function short(v) { return v.length > 90 ? v.slice(0, 90) + '… (' + v.length + ' chars)' : v; }
      function update() {
        var sent = S.sent();
        var tbody = root.querySelector('.debug-values tbody');
        tbody.innerHTML = '';
        KEYS.forEach(function (k) {
          var tr = document.createElement('tr');
          var th = document.createElement('th'); th.scope = 'row'; th.textContent = k.replace('cmi.core.', '').replace('cmi.', '');
          var td = document.createElement('td'); td.textContent = sent[k] === undefined ? '—' : (short(sent[k]) || '""');
          tr.append(th, td);
          tbody.appendChild(tr);
        });
        root.querySelector('.debug-summary').textContent =
          'status: ' + (sent['cmi.core.lesson_status'] || '—') +
          ' · score: ' + (sent['cmi.core.score.raw'] || '—') +
          ' · bookmark: ' + (sent['cmi.core.lesson_location'] !== undefined ? sent['cmi.core.lesson_location'] : '—');
        var ol = root.querySelector('.debug-log');
        ol.innerHTML = '';
        S.log().slice(-60).reverse().forEach(function (e) {
          var li = document.createElement('li');
          var args = e.args.map(function (a) { return JSON.stringify(short(String(a))); }).join(', ');
          li.textContent = e.fn + '(' + args + ') → ' + JSON.stringify(e.result) + (e.error ? '  ⚠ ' + e.error : '');
          if (e.error) li.className = 'debug-err';
          ol.appendChild(li);
        });
      }
      S.onLog(update);
      update();
    }
  };
})();
