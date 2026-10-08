/* bm-visitor-id — who read this page, on how many days, and what they touched.
   Source of truth: bricks/scripts/outreach/reader_events.js (inlined by visitor_id.py
   into every /for/ page; pasted verbatim into buying-window, pt-rates, salon-rates).

   PostHog keeps an anonymous distinct_id in localStorage + cookie, so a return
   visit on another day is the same reader (Vercel's hash rotates daily). Every
   event also goes to Vercel custom events (va.track) so the dashboard shows it.

   Events: $pageview (auto), download, sort, filter, row_click, row_expand,
   link_click, scroll_depth (25/50/75/100), time_on_page (seconds visible). */
(function () {
  var KEY = 'phc_yFgRGppL6H7DvhgZTQKbHdrY5oqnpLT482rrNYtLqnAx';
  var q = [], ready = false;
  window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
  function cut(v) { return String(v == null ? '' : v).replace(/\s+/g, ' ').trim().slice(0, 120); }
  function send(name, props, beacon) {
    props = props || {};
    try { window.va('event', { name: name, data: props }); } catch (e) {}
    if (ready) { try { posthog.capture(name, props, beacon ? { transport: 'sendBeacon' } : undefined); } catch (e) {} }
    else q.push([name, props]);
  }
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://us-assets.i.posthog.com/static/array.js';
  s.onload = function () {
    posthog.init(KEY, { api_host: 'https://us.i.posthog.com', person_profiles: 'identified_only',
                        persistence: 'localStorage+cookie' });
    posthog.register({ site: location.hostname, path: location.pathname });
    ready = true;
    while (q.length) { var e = q.shift(); posthog.capture(e[0], e[1]); }
  };
  document.head.appendChild(s);

  function label(el) {
    return cut(el.getAttribute('aria-label') || el.name || el.id || el.getAttribute('placeholder') || 'control');
  }
  function rowText(el) {
    var k = el.querySelector('.a, .name, td, summary, b, strong');
    return cut((k || el).textContent);
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    var a = t.closest('a[href]');
    if (a) {
      var h = a.getAttribute('href') || '';
      if (a.hasAttribute('download') || /\.csv(\?|$)|\/api\/export/.test(h)) {
        send('download', { file: cut(a.getAttribute('download') || h.split('?')[0].split('/').pop() || a.textContent), href: cut(h) });
      } else {
        send('link_click', { href: cut(a.href), text: cut(a.textContent) });
      }
      return;
    }
    var th = t.closest('th');
    if (th) { send('sort', { column: cut(th.textContent) }); return; }
    var opt = t.closest('[role=option]');
    if (opt) { send('row_click', { row: cut((opt.firstElementChild || opt).textContent) }); return; }
    var chip = t.closest('.chip, [aria-pressed], [role=tab]');
    if (chip) {
      var grp = chip.parentElement;
      send('filter', { column: cut((grp && (grp.getAttribute('aria-label') || grp.id)) || 'chips'), value: cut(chip.textContent) });
      return;
    }
    var pick = t.closest('button[data-id], button[data-slug], [data-row]');
    if (pick) { send('row_click', { row: cut(pick.textContent) }); return; }
    if (t.closest('summary')) return; /* counted by the toggle listener */
    var row = t.closest('tbody tr, ol > li, ul > li, tr[class]');
    if (row && !t.closest('nav, header, footer')) { send('row_click', { row: rowText(row) }); return; }
    var b = t.closest('button');
    if (b) send('button', { id: cut(b.id || b.textContent) });
  }, true);

  document.addEventListener('change', function (ev) {
    var el = ev.target;
    if (!el || el.tagName !== 'SELECT') return;
    var v = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value;
    send(/sort|order/i.test(el.id + ' ' + el.name) ? 'sort' : 'filter', { column: label(el), value: cut(v) });
  }, true);

  var typing = {};
  document.addEventListener('input', function (ev) {
    var el = ev.target;
    if (!el || el.tagName !== 'INPUT' || !/^(search|text)$/.test(el.type)) return;
    var k = label(el);
    clearTimeout(typing[k]);
    typing[k] = setTimeout(function () { if (el.value.trim()) send('filter', { column: k, value: cut(el.value) }); }, 900);
  }, true);

  document.addEventListener('toggle', function (ev) {
    var d = ev.target;
    if (d && d.tagName === 'DETAILS' && d.open) {
      var sm = d.querySelector('summary');
      send('row_expand', { row: cut(sm ? sm.textContent : d.textContent) });
    }
  }, true);

  var marks = [25, 50, 75, 100], hit = 0;
  function depth() {
    var de = document.documentElement;
    var seen = (window.scrollY + window.innerHeight) / Math.max(de.scrollHeight, 1) * 100;
    while (marks.length && seen >= marks[0] - 1) { hit = marks.shift(); send('scroll_depth', { depth: hit }); }
  }
  window.addEventListener('scroll', depth, { passive: true });
  window.addEventListener('load', depth);

  var shown = 0, since = document.visibilityState === 'visible' ? Date.now() : 0;
  function flush() {
    if (since) { shown += Date.now() - since; since = 0; }
    if (shown >= 1000) send('time_on_page', { seconds: Math.round(shown / 1000), max_depth: hit }, true);
    shown = 0;
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush(); else since = Date.now();
  });
  window.addEventListener('pagehide', flush);
})();
