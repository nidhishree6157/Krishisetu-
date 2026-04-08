// KrishiSetu - Main Application
// ==============================

class KrishiSetu {
  constructor() {
    this.currentPage = null;
    this.userRole = localStorage.getItem('userRole') || 'farmer';
    this.authToken = localStorage.getItem('authToken');
    this.apiBase = 'http://127.0.0.1:5000';
    this.init();
  }

  init() {
    this.setupEventListeners();
  }

  setupEventListeners() {
    document.addEventListener('DOMContentLoaded', () => {
      this.attachNavigation();
      this.attachHamburger();
      this.attachLogout();
      this.attachNotification();
      this.attachProfileIcon();
    });
  }

  attachHamburger() {
    const hamburger = document.querySelector('.hamburger');
    const sidebar = document.querySelector('.sidebar');
    if (hamburger && sidebar) {
      hamburger.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
      });
    }
  }

  // ── Notification system ────────────────────────────────────────────────────
  attachNotification() {
    const notifIcon = document.querySelector('.notification-icon');
    if (!notifIcon || notifIcon.dataset.notifBound) return;
    notifIcon.dataset.notifBound = '1';

    // Inject CSS (once per page)
    if (!document.getElementById('_ks_notif_css')) {
      const s = document.createElement('style');
      s.id = '_ks_notif_css';
      s.textContent = `
        .notification-icon { position:relative; cursor:pointer; user-select:none; }
        .notif-dropdown {
          display:none; position:absolute; top:calc(100% + 12px); right:-8px;
          width:330px; background:#fff; border:1px solid #e5e7eb;
          border-radius:14px; box-shadow:0 20px 50px rgba(0,0,0,0.15);
          z-index:9999; overflow:hidden;
        }
        .notif-dropdown.open {
          display:block;
          animation:_ksNSlide .18s ease;
        }
        @keyframes _ksNSlide {
          from { opacity:0; transform:translateY(-8px); }
          to   { opacity:1; transform:translateY(0); }
        }
        .notif-hdr {
          display:flex; justify-content:space-between; align-items:center;
          padding:13px 16px 10px; border-bottom:1px solid #f3f4f6;
          font-weight:700; font-size:13.5px; color:#111827;
        }
        .notif-mark-all {
          font-size:11.5px; color:#2e7d32; background:none; border:none;
          cursor:pointer; font-weight:600; padding:0;
        }
        .notif-mark-all:hover { text-decoration:underline; }
        .notif-list { max-height:310px; overflow-y:auto; }
        .notif-item {
          display:flex; align-items:flex-start; gap:10px;
          padding:11px 16px; border-bottom:1px solid #f9fafb;
          cursor:pointer; transition:background .12s;
        }
        .notif-item:hover  { background:#f9fafb; }
        .notif-item.unread { background:#f0fdf4; }
        .notif-item.unread:hover { background:#dcfce7; }
        .notif-ico {
          width:32px; height:32px; border-radius:50%;
          display:flex; align-items:center; justify-content:center;
          font-size:13px; flex-shrink:0; margin-top:1px;
        }
        .notif-ico.disease { background:#fee2e2; color:#b91c1c; }
        .notif-ico.expert  { background:#dbeafe; color:#1e40af; }
        .notif-ico.info    { background:#f3f4f6; color:#6b7280; }
        .notif-body  { flex:1; min-width:0; }
        .notif-msg   { font-size:12.5px; color:#374151; line-height:1.45; }
        .notif-time  { font-size:11px; color:#9ca3af; margin-top:3px; }
        .notif-dot   {
          width:7px; height:7px; border-radius:50%;
          background:#2e7d32; flex-shrink:0; margin-top:6px;
        }
        .notif-empty { padding:28px 16px; text-align:center; color:#9ca3af; font-size:13px; }
        .notif-footer {
          padding:10px 16px; text-align:center; border-top:1px solid #f3f4f6;
          font-size:12.5px; color:#2e7d32; font-weight:600; cursor:pointer;
        }
        .notif-footer:hover { background:#f9fafb; }
        #_ks_notif_badge {
          position:absolute; top:-5px; right:-6px;
          background:#ef4444; color:#fff; border-radius:10px;
          font-size:10px; font-weight:700; padding:1px 5px;
          min-width:16px; text-align:center; line-height:16px;
          pointer-events:none;
        }
        #_ks_notif_badge[data-count="0"] { display:none; }
      `;
      document.head.appendChild(s);
    }

    // Inject dynamic badge (replaces static .notification-badge)
    const existingBadge = notifIcon.querySelector('.notification-badge');
    if (existingBadge) existingBadge.remove();
    const badge = document.createElement('div');
    badge.id = '_ks_notif_badge';
    badge.dataset.count = '0';
    badge.textContent = '0';
    notifIcon.appendChild(badge);

    // Inject dropdown (once)
    if (!document.getElementById('_ks_notif_dropdown')) {
      const dd = document.createElement('div');
      dd.id = '_ks_notif_dropdown';
      dd.className = 'notif-dropdown';
      dd.innerHTML = `
        <div class="notif-hdr">
          <span>🔔 Notifications</span>
          <button class="notif-mark-all" id="_ks_mark_all">Mark all read</button>
        </div>
        <div class="notif-list" id="_ks_notif_list">
          <div class="notif-empty">Loading…</div>
        </div>
        <div class="notif-footer" id="_ks_notif_footer">View all notifications</div>
      `;
      notifIcon.appendChild(dd);
    }

    // Toggle on bell click
    notifIcon.addEventListener('click', (e) => {
      const dd = document.getElementById('_ks_notif_dropdown');
      if (!dd) return;
      const opening = !dd.classList.contains('open');
      dd.classList.toggle('open');
      if (opening) this.fetchNotifications();
      e.stopPropagation();
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      const dd = document.getElementById('_ks_notif_dropdown');
      if (dd && !notifIcon.contains(e.target)) dd.classList.remove('open');
    });

    // Mark all read
    document.addEventListener('click', (e) => {
      if (e.target && e.target.id === '_ks_mark_all') {
        e.stopPropagation();
        this.markAllNotificationsRead();
      }
    });

    // Start polling
    this.fetchNotifications();
    if (!this._notifPollId) {
      this._notifPollId = setInterval(() => this.fetchNotifications(), 10000);
    }
  }

  async fetchNotifications() {
    try {
      const res  = await fetch(`${this.apiBase}/notifications/`, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      if (!data.success) return;
      // Cache the full list so markAllNotificationsRead() can use every ID
      this._lastNotifications = data.notifications || [];
      this._renderNotifications(this._lastNotifications, data.unread_count || 0);
    } catch (e) {
      // Network error — silently ignore during polling
    }
  }

  _renderNotifications(notifications, unreadCount) {
    // Update badge
    const badge = document.getElementById('_ks_notif_badge');
    if (badge) {
      badge.dataset.count = unreadCount;
      badge.textContent   = unreadCount > 9 ? '9+' : String(unreadCount);
      badge.style.display = unreadCount > 0 ? '' : 'none';
    }

    // Also update legacy .notification-badge if present (other pages)
    const legacyBadge = document.querySelector('.notification-badge:not(#_ks_notif_badge)');
    if (legacyBadge) legacyBadge.textContent = unreadCount;

    const list = document.getElementById('_ks_notif_list');
    if (!list) return;

    if (!notifications || notifications.length === 0) {
      list.innerHTML = '<div class="notif-empty"><i class="fas fa-bell-slash" style="display:block;font-size:22px;margin-bottom:8px;"></i>No notifications yet</div>';
      return;
    }

    const iconMap = { disease: 'fas fa-virus', expert: 'fas fa-user-tie', info: 'fas fa-info-circle' };
    const typeClass = { disease: 'disease', expert: 'expert' };

    list.innerHTML = notifications.slice(0, 5).map(n => {
      const ico   = iconMap[n.type] || iconMap.info;
      const cls   = typeClass[n.type] || 'info';
      const unread = !n.read;
      return `
        <div class="notif-item ${unread ? 'unread' : ''}"
             data-ref="${this._esc(n.id)}"
             onclick="app._onNotifClick(this,'${this._esc(n.id)}')">
          <div class="notif-ico ${cls}"><i class="${ico}"></i></div>
          <div class="notif-body">
            <div class="notif-msg">${this._esc(n.message)}</div>
            <div class="notif-time">${this._esc(n.time_label || n.time || '')}</div>
          </div>
          ${unread ? '<div class="notif-dot"></div>' : ''}
        </div>
      `;
    }).join('');
  }

  _esc(str) {
    return String(str || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
      .replace(/'/g,'&#039;');
  }

  async _onNotifClick(el, ref) {
    if (!ref) return;
    el.classList.remove('unread');
    const dot = el.querySelector('.notif-dot');
    if (dot) dot.remove();
    await this._markRead([ref]);
    await this.fetchNotifications();
  }

  async markAllNotificationsRead() {
    // Use the full cached list — not just the 5 items in the DOM
    const allNotifs = this._lastNotifications || [];
    const ids = allNotifs.map(n => n.id).filter(Boolean);

    if (!ids.length) return;

    // ── Instant UI feedback (no waiting for server) ────────────────────────
    // Zero the badge immediately
    const badge = document.getElementById('_ks_notif_badge');
    if (badge) {
      badge.textContent   = '0';
      badge.style.display = 'none';
      badge.dataset.count = '0';
    }
    const legacyBadge = document.querySelector('.notification-badge:not(#_ks_notif_badge)');
    if (legacyBadge) legacyBadge.textContent = '0';

    // Remove unread styling from every visible item
    document.querySelectorAll('.notif-item.unread').forEach(el => {
      el.classList.remove('unread');
      const dot = el.querySelector('.notif-dot');
      if (dot) dot.remove();
    });

    // Mark the button as done while request is in flight
    const btn = document.getElementById('_ks_mark_all');
    if (btn) { btn.textContent = 'Marking…'; btn.disabled = true; }

    // ── POST all IDs to backend ────────────────────────────────────────────
    await this._markRead(ids);

    // Restore button + refresh list from server
    if (btn) { btn.textContent = 'All read ✓'; btn.disabled = false; }
    setTimeout(() => { if (btn) btn.textContent = 'Mark all read'; }, 2000);

    // Update cached list so repeated clicks don't re-send
    if (this._lastNotifications) {
      this._lastNotifications = this._lastNotifications.map(n => ({ ...n, read: true }));
    }

    // Async refresh to sync server state (don't await — non-blocking)
    this.fetchNotifications();
  }

  async _markRead(refs) {
    if (!refs || !refs.length) return;
    try {
      const res = await fetch(`${this.apiBase}/notifications/read`, {
        method:      'POST',
        headers:     { 'Content-Type': 'application/json' },
        credentials: 'include',
        body:        JSON.stringify({ ids: refs }),
      });
      if (!res.ok) {
        console.warn('[Notifications] mark-read HTTP', res.status);
      }
    } catch (e) {
      console.warn('[Notifications] mark-read network error', e);
    }
  }

  attachProfileIcon() {
    const profileIcon = document.querySelector('.profile-icon');
    if (!profileIcon) return;
    // Navigate to the profile page — title-bar icon now acts as "My Profile" link.
    profileIcon.style.cursor = 'pointer';
    profileIcon.title = 'My Profile';
    profileIcon.addEventListener('click', () => {
      window.location.href = 'profile.html';
    });
  }

  attachNavigation() {
    const navLinks = document.querySelectorAll('.nav-link');
    if (!navLinks.length) return;
    
    navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        const page = link.dataset?.page;
        if (page) {
          e.preventDefault();
          this.navigate(page);
          navLinks.forEach(l => l.classList.remove('active'));
          link.classList.add('active');
        }
      });
    });
  }

  attachLogout() {
    const logoutBtn = document.querySelector('.logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => {
        this.logout();
      });
    }
  }

  navigate(page) {
    if (!page) return;
    window.location.href = `${page}.html`;
  }

  async logout() {
    try {
      const response = await fetch(`${this.apiBase}/auth/logout`, {
        method: 'POST',
        credentials: 'include'
      });
      
      if (!response.ok) {
        console.warn('Logout API returned:', response.status);
      }
    } catch (e) {
      console.warn('Logout API error:', e.message);
    }
    
    localStorage.clear();
    sessionStorage.clear();
    window.location.href = 'login.html';
  }

  showLoading(element) {
    element.innerHTML = '<div class="loading-container"><div class="loading-spinner"></div><p class="loading-text">Processing...</p></div>';
  }

  showAlert(container, message, type = 'success') {
    const iconMap = { success: '✓', danger: '✕', info: 'ℹ' };
    const html = `<div class="alert alert-${type}"><span class="alert-icon">${iconMap[type]}</span>${message}</div>`;
    container.insertAdjacentHTML('beforeend', html);
    setTimeout(() => container.lastChild?.remove(), 4000);
  }

  async apiCall(endpoint, method = 'GET', data = null, formData = null) {
    const options = {
      method,
      credentials: 'include',   
      headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {}
    };

    if (formData) {
      options.body = formData;
    } else {
      options.headers = options.headers || {};
      options.headers['Content-Type'] = 'application/json';
      if (data) options.body = JSON.stringify(data);
    }
    
    try {
      const response = await fetch(`${this.apiBase}${endpoint}`, options);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const msg = data.message || data.error || `HTTP ${response.status}`;
        const err = new Error(msg);
        err.response = data;
        err.status = response.status;
        throw err;
      }
      return data;
    } catch (error) {
      console.error('API Error:', error);
      throw error;
    }
  }

  formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
  }

  showNotification(message, type = 'info') {
    const badge = document.querySelector('.notification-badge');
    if (badge) {
      badge.textContent = parseInt(badge.textContent || 0) + 1;
    }
  }
}

// Initialize on load
const app = new KrishiSetu();

// Global wrapper functions
function attachNavigation() { app.attachNavigation(); }
function attachHamburger() { app.attachHamburger(); }
function attachLogout() { app.attachLogout(); }

// Utilities
function setButtonLoading(btn, isLoading) {
  if (isLoading) {
    btn.disabled = true;
    btn.classList.add('btn-loading');
    btn.dataset.originalText = btn.textContent;
  } else {
    btn.disabled = false;
    btn.classList.remove('btn-loading');
    btn.textContent = btn.dataset.originalText || btn.textContent;
  }
}

function validateForm(formElement) {
  const requiredFields = formElement.querySelectorAll('[required]');
  for (let field of requiredFields) {
    if (!field.value.trim()) {
      app.showAlert(formElement, `Please fill in all required fields`, 'danger');
      return false;
    }
  }
  return true;
}

function clearForm(formElement) {
  formElement.reset();
  const previews = formElement.querySelectorAll('img.image-preview');
  previews.forEach(p => p.remove());
}

function setActiveNav(pageId) {
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  const active = document.querySelector(`[data-page="${pageId}"]`);
  if (active) active.classList.add('active');
}

function displayRecommendation(data) {
  const resultDiv = document.querySelector("#result");
  if (!resultDiv || !data) return;

  console.log("displayRecommendation data:", data);

  const crop = data.crop ?? "";
  const seeds = Array.isArray(data.seeds) ? data.seeds : [];
  const fertilizerValue = Array.isArray(data.fertilizer)
    ? data.fertilizer.join(", ")
    : (data.fertilizer ?? "");

  let html = `
    <h3>Recommended Crop</h3>
    <p>${crop}</p>
    <h3>Best Seeds</h3>
    <ul>
      ${seeds.map(s => `<li>${typeof s === "string" ? s : (s?.name ?? "")}</li>`).filter(item => item !== "<li></li>").join("")}
    </ul>
    <p><b>Fertilizer:</b> ${fertilizerValue}</p>
  `;

  html += `
    <button id="askExpertBtn" class="btn btn-secondary" style="margin-top: 12px;">Ask Expert</button>
    <div id="expertStatus" style="margin-top:10px; color: var(--text-light);"></div>
  `;

  resultDiv.style.display = "block";
  resultDiv.innerHTML = html;

  const askExpertBtn = document.querySelector("#askExpertBtn");
  if (askExpertBtn) {
    askExpertBtn.addEventListener("click", askExpert);
  }
}

function getRecommendation(event) {
  if (event) event.preventDefault();

  console.log("Get Recommendation clicked");

  const selectedCrop = document.querySelector("#crop")?.value || "";
  const selectedLocation = document.querySelector("#location")?.value || "";
  const selectedMode = document.querySelector("#mode")?.value || "new";
  const resultDiv = document.querySelector("#result");

  if (resultDiv) {
    resultDiv.innerHTML = "⏳ Processing...";
  }

  const payload = {
    crop: selectedCrop || "",
    location: selectedLocation || "",
    mode: selectedMode || "new"
  };

  fetch("http://127.0.0.1:5000/api/recommend", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    credentials: "include",
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      console.log("Recommendation Response:", data);
      console.log("crop:", data?.crop, "seeds:", data?.seeds);
      window.latestRecommendation = data;
      if (!data || data.success === false) {
        const msg = data?.message || "Recommendation failed.";
        if (resultDiv) resultDiv.innerHTML = `<p class="text-danger">❌ ${msg}</p>`;
        return;
      }
      displayRecommendation(data);
    })
    .catch(err => {
      console.error("Recommendation Error:", err);
      if (resultDiv) {
        resultDiv.innerHTML = "❌ Server error. Please try again.";
      }
    });
}

function askExpert() {
  console.log("Ask Expert clicked");

  if (!window.latestRecommendation) {
    console.error("No recommendation data available");
    return;
  }

  const rec = window.latestRecommendation;
  if (rec.success === false) return;
  const fertilizerValue = Array.isArray(rec.fertilizer)
    ? rec.fertilizer.join(", ")
    : (rec.fertilizer ?? "");

  const payload = {
    crop: rec.crop ?? "",
    location: rec.location || "",
    mode: rec.mode || "",
    fertilizer: fertilizerValue,
    query_text: `Crop: ${rec.crop || ""} | Location: ${rec.location || ""} | Mode: ${rec.mode || ""} | Fertilizer: ${fertilizerValue}`
  };

  fetch("http://127.0.0.1:5000/expert/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    credentials: "include",
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      console.log("Expert Response:", data);
      const expertStatus = document.querySelector("#expertStatus");
      if (expertStatus) {
        expertStatus.innerHTML = data?.success
          ? "✅ Query sent to expert successfully."
          : `❌ ${data?.message || "Failed to send query."}`;
      }
    })
    .catch(err => {
      console.error("Expert Error:", err);
      const expertStatus = document.querySelector("#expertStatus");
      if (expertStatus) {
        expertStatus.innerHTML = "❌ Failed to send query.";
      }
    });
}

document.addEventListener("DOMContentLoaded", function () {
  const recommendationForm = document.querySelector("#recommendationForm");
  const getRecommendationBtn = document.querySelector("#getRecommendationBtn");
  const askExpertBtn = document.querySelector("#askExpertBtn");

  if (recommendationForm) {
    recommendationForm.addEventListener("submit", getRecommendation);
  } else if (getRecommendationBtn) {
    getRecommendationBtn.addEventListener("click", getRecommendation);
  }

  if (askExpertBtn) {
    askExpertBtn.addEventListener("click", askExpert);
  }
});