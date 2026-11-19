/* =====================================================================
   Lightweight SCORM 1.2 wrapper  (window.SCORM)
   ---------------------------------------------------------------------
   - Looks for the LMS's "API" object in parent frames / the opener window
     (that is how SCORM 1.2 LMSs expose themselves to a course).
   - If no LMS is found (e.g. you opened index.html straight from disk),
     it uses a MOCK LMS that behaves like a real one and saves to the
     browser's localStorage, so bookmarking and resume can be tested.
   - Every call is logged so the debug panel can show what would be sent.
   ===================================================================== */
(function (global) {
  'use strict';

  var logEntries = [];
  var listeners = [];
  var sent = {};          // last value read from or set on the LMS, per element

  function record(fn, args, result, error) {
    var entry = { time: new Date(), fn: fn, args: args, result: result, error: error || '' };
    logEntries.push(entry);
    if (logEntries.length > 400) logEntries.shift();
    listeners.forEach(function (cb) { try { cb(entry); } catch (e) { /* ignore */ } });
  }

  /* ---------- Finding the LMS API ---------- */
  function scan(win) {
    var depth = 0;
    while (win && depth <= 10) {
      try { if (win.API) return win.API; } catch (e) { /* cross-origin frame */ }
      var parent = null;
      try { parent = win.parent; } catch (e) { parent = null; }
      if (!parent || parent === win) break;
      win = parent;
      depth++;
    }
    return null;
  }
  function findLmsApi() {
    var api = scan(global);
    if (!api) { try { if (global.opener) api = scan(global.opener); } catch (e) { /* ignore */ } }
    return api;
  }

  /* ---------- Mock LMS (preview mode) ---------- */
  var READ_ONLY = ['cmi.core.student_id', 'cmi.core.student_name', 'cmi.core.entry', 'cmi.core.credit',
                   'cmi.core.lesson_mode', 'cmi.core.total_time', 'cmi.launch_data', 'cmi.core._children'];
  var WRITE_ONLY = ['cmi.core.exit', 'cmi.core.session_time'];
  var STATUSES = ['passed', 'completed', 'failed', 'incomplete', 'browsed', 'not attempted'];
  var EXITS = ['', 'time-out', 'suspend', 'logout'];
  var ERRORS = { '0': 'No error', '101': 'General exception', '201': 'Invalid argument error',
                 '301': 'Not initialized', '401': 'Not implemented error', '403': 'Element is read only',
                 '404': 'Element is write only', '405': 'Incorrect data type' };

  function MockLMS(courseId) {
    this.storageKey = 'scorm12-preview:' + courseId;
    this.running = false;
    this.lastError = '0';
    this.data = {};
    try { this.data = JSON.parse(global.localStorage.getItem(this.storageKey)) || {}; } catch (e) { this.data = {}; }
  }
  MockLMS.prototype._save = function () {
    try { global.localStorage.setItem(this.storageKey, JSON.stringify(this.data)); } catch (e) { /* private mode */ }
  };
  MockLMS.prototype._ok = function (v) { this.lastError = '0'; return v; };
  MockLMS.prototype._fail = function (code, v) { this.lastError = code; return v; };

  MockLMS.prototype.LMSInitialize = function (arg) {
    if (arg !== '') return this._fail('201', 'false');
    if (this.running) return this._fail('101', 'false');
    var d = this.data;
    var returning = d['cmi.core.lesson_status'] !== undefined;
    d['cmi.core.entry'] = d['cmi.core.exit'] === 'suspend' ? 'resume' : (returning ? '' : 'ab-initio');
    var defaults = {
      'cmi.core.student_id': 'preview-learner', 'cmi.core.student_name': 'Learner, Preview',
      'cmi.core.lesson_status': 'not attempted', 'cmi.core.lesson_location': '', 'cmi.core.credit': 'credit',
      'cmi.core.lesson_mode': 'normal', 'cmi.core.score.raw': '', 'cmi.core.score.min': '', 'cmi.core.score.max': '',
      'cmi.core.total_time': '0000:00:00', 'cmi.suspend_data': '', 'cmi.launch_data': ''
    };
    Object.keys(defaults).forEach(function (k) { if (d[k] === undefined) d[k] = defaults[k]; });
    d['cmi.core.exit'] = '';
    d['cmi.core.session_time'] = '';
    this.running = true;
    this._save();
    return this._ok('true');
  };
  MockLMS.prototype.LMSFinish = function (arg) {
    if (arg !== '') return this._fail('201', 'false');
    if (!this.running) return this._fail('301', 'false');
    this.running = false;
    this._save();
    return this._ok('true');
  };
  MockLMS.prototype.LMSGetValue = function (key) {
    if (!this.running) return this._fail('301', '');
    if (WRITE_ONLY.indexOf(key) >= 0) return this._fail('404', '');
    if (key === 'cmi.core._children') return this._ok('student_id,student_name,lesson_location,credit,lesson_status,entry,score,total_time,lesson_mode,exit,session_time');
    if (this.data[key] === undefined) return this._fail('401', '');
    return this._ok(String(this.data[key]));
  };
  MockLMS.prototype.LMSSetValue = function (key, value) {
    if (!this.running) return this._fail('301', 'false');
    if (READ_ONLY.indexOf(key) >= 0) return this._fail('403', 'false');
    value = String(value);
    if (key === 'cmi.core.lesson_status' && (STATUSES.indexOf(value) < 0 || value === 'not attempted')) return this._fail('405', 'false');
    if (key === 'cmi.core.exit' && EXITS.indexOf(value) < 0) return this._fail('405', 'false');
    if (/^cmi\.core\.score\.(raw|min|max)$/.test(key) && value !== '' && !(Number(value) >= 0 && Number(value) <= 100)) return this._fail('405', 'false');
    if (key === 'cmi.core.lesson_location' && value.length > 255) return this._fail('405', 'false');
    if (key === 'cmi.suspend_data' && value.length > 4096) return this._fail('405', 'false');
    if (key === 'cmi.core.session_time' && !/^\d{2,4}:\d{2}:\d{2}(\.\d{1,2})?$/.test(value)) return this._fail('405', 'false');
    this.data[key] = value;
    return this._ok('true');
  };
  MockLMS.prototype.LMSCommit = function (arg) {
    if (arg !== '') return this._fail('201', 'false');
    if (!this.running) return this._fail('301', 'false');
    this._save();
    return this._ok('true');
  };
  MockLMS.prototype.LMSGetLastError = function () { return this.lastError; };
  MockLMS.prototype.LMSGetErrorString = function (code) { return ERRORS[String(code)] || 'Unknown error'; };
  MockLMS.prototype.LMSGetDiagnostic = function (code) { return this.LMSGetErrorString(code || this.lastError); };

  /* ---------- Wrapper ---------- */
  function isTrue(r) { return r === true || r === 'true'; }

  function call(fn, args) {
    var api = SCORM.api, result, error = '';
    try {
      result = api[fn].apply(api, args);
    } catch (e) {
      result = 'false';
      error = 'Exception: ' + e.message;
    }
    if (!error) {
      try {
        var code = String(api.LMSGetLastError());
        if (code && code !== '0') error = code + ' ' + api.LMSGetErrorString(code);
      } catch (e) { /* ignore */ }
    }
    record(fn, args, result, error);
    return result;
  }

  var SCORM = {
    api: null,
    isMock: false,
    active: false,

    init: function (courseId) {
      var api = findLmsApi();
      if (!api) { api = new MockLMS(courseId); this.isMock = true; }
      this.api = api;
      this.active = isTrue(call('LMSInitialize', ['']));
      return this.active;
    },
    get: function (key) {
      if (!this.active) return '';
      var v = call('LMSGetValue', [key]);
      v = v == null ? '' : String(v);
      if (sent[key] === undefined) sent[key] = v;   // so the debug panel shows resumed values too
      return v;
    },
    set: function (key, value) {
      if (!this.active) return false;
      var ok = isTrue(call('LMSSetValue', [key, String(value)]));
      if (ok) sent[key] = String(value);
      return ok;
    },
    commit: function () { return this.active ? isTrue(call('LMSCommit', [''])) : false; },
    finish: function () {
      if (!this.active) return false;
      this.active = false;
      return isTrue(call('LMSFinish', ['']));
    },
    /* For the debug panel */
    onLog: function (cb) { listeners.push(cb); },
    log: function () { return logEntries.slice(); },
    sent: function () { return Object.assign({}, sent); },
    resetPreview: function () {
      if (this.isMock) { try { global.localStorage.removeItem(this.api.storageKey); } catch (e) { /* ignore */ } }
    },
    /* SCORM 1.2 time format: HHHH:MM:SS.SS */
    formatTime: function (ms) {
      var total = Math.max(0, ms) / 1000;
      var h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
      function pad(n, w) { n = String(n); while (n.length < w) n = '0' + n; return n; }
      return pad(Math.min(h, 9999), 4) + ':' + pad(m, 2) + ':' + pad(s.toFixed(2), 5);
    }
  };

  global.SCORM = SCORM;
})(window);
