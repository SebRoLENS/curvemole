/* Optional site analytics: nothing from Google loads before explicit consent. */
(() => {
  'use strict';
  const id = 'G-WZS7HDJ5QB';
  const key = 'curvemole-analytics-consent-v1';
  const maxAge = 180 * 24 * 60 * 60 * 1000;
  let started = false;
  window['ga-disable-' + id] = true;

  function getChoice() {
    try {
      const saved = JSON.parse(localStorage.getItem(key));
      if (saved && ['accepted', 'rejected'].includes(saved.value) &&
          Number.isFinite(saved.timestamp) && saved.timestamp <= Date.now() &&
          Date.now() - saved.timestamp < maxAge) return saved.value;
    } catch (_) { /* Private browsing or unavailable local storage. */ }
    return null;
  }

  function saveChoice(value) {
    try {
      localStorage.setItem(key, JSON.stringify({ value, timestamp: Date.now() }));
    } catch (_) { /* An in-memory choice still works during this visit. */ }
  }

  function clearAnalyticsCookies() {
    document.cookie.split(';').forEach(item => {
      const name = item.trim().split('=')[0];
      if (!/^(_ga(?:_|$)|_gid$|_gat(?:_|$))/.test(name)) return;
      for (const path of ['/', '/curvemole', '/curvemole/']) {
        document.cookie = name + '=; Max-Age=0; path=' + path + '; SameSite=Lax';
      }
    });
  }

  function enableAnalytics() {
    window['ga-disable-' + id] = false;
    if (started) {
      if (typeof window.gtag === 'function') {
        window.gtag('consent', 'update', { analytics_storage: 'granted' });
      }
      return;
    }
    started = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {
      analytics_storage: 'granted',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied'
    });
    window.gtag('js', new Date());
    window.gtag('config', id, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false
    });
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
    document.head.appendChild(script);
  }

  function disableAnalytics() {
    window['ga-disable-' + id] = true;
    if (typeof window.gtag === 'function') {
      window.gtag('consent', 'update', {
        analytics_storage: 'denied',
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied'
      });
    }
    clearAnalyticsCookies();
  }

  const banner = document.createElement('section');
  banner.className = 'analytics-consent-banner';
  banner.id = 'analytics-consent-banner';
  banner.setAttribute('role', 'region');
  banner.setAttribute('aria-labelledby', 'analytics-consent-title');
  banner.hidden = true;
  banner.innerHTML = `
    <div class="analytics-consent-copy">
      <h2 id="analytics-consent-title">Optional website analytics</h2>
      <p>CurveMole uses Google Analytics to understand how visitors use this
      website. Google Analytics runs <strong>only if you agree</strong>.
      You can change your choice anytime.
      <a href="privacy.html">Privacy &amp; cookie information</a>.</p>
    </div>
    <div class="analytics-consent-actions">
      <button type="button" data-analytics-choice="rejected">Reject</button>
      <button type="button" class="analytics-accept" data-analytics-choice="accepted">Allow analytics</button>
    </div>`;
  banner.addEventListener('click', event => {
    const button = event.target.closest('[data-analytics-choice]');
    if (!button) return;
    const choice = button.dataset.analyticsChoice;
    saveChoice(choice);
    if (choice === 'accepted') enableAnalytics();
    else disableAnalytics();
    banner.hidden = true;
  });
  document.body.appendChild(banner);

  const preferences = document.getElementById('cookiePreferences');
  if (preferences) {
    preferences.addEventListener('click', () => {
      banner.hidden = false;
      banner.querySelector('button').focus();
    });
  }
  const previous = getChoice();
  if (previous === 'accepted') enableAnalytics();
  else if (previous === 'rejected') disableAnalytics();
  else banner.hidden = false;
  if (location.hash === '#cookie-preferences') banner.hidden = false;
})();
