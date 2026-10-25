/**
 * AICTE Centralized API Client with JWT Authentication, Error Interception,
 * XSS Prevention Sanitization, and Shared Dashboard Helpers.
 */
const API_BASE = window.location.origin;

const API = {
  getToken() {
    return localStorage.getItem("aicte_token");
  },

  setToken(token) {
    if (token) {
      localStorage.setItem("aicte_token", token);
    } else {
      localStorage.removeItem("aicte_token");
    }
  },

  getUser() {
    try {
      const u = localStorage.getItem("aicte_user");
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  },

  setUser(user) {
    if (user) {
      localStorage.setItem("aicte_user", JSON.stringify(user));
    } else {
      localStorage.removeItem("aicte_user");
    }
  },

  clearAuth() {
    localStorage.removeItem("aicte_token");
    localStorage.removeItem("aicte_user");
  },

  async request(endpoint, options = {}) {
    const defaultHeaders = {
      "Accept": "application/json",
    };

    // Only set Content-Type if body is not FormData (browser sets boundary for FormData)
    if (!(options.body instanceof FormData)) {
      defaultHeaders["Content-Type"] = "application/json";
    }

    const token = this.getToken();
    if (token) {
      defaultHeaders["Authorization"] = `Bearer ${token}`;
    }

    const config = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...(options.headers || {}),
      },
    };

    try {
      const response = await fetch(`${API_BASE}${endpoint}`, config);

      // Auto-handle 401 Unauthorized by logging out if accessing protected resources
      if (response.status === 401 && !endpoint.includes("/login")) {
        this.clearAuth();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login?session_expired=1";
        }
      }

      let data;
      const contentType = response.headers.get("content-type");
      if (contentType && contentType.includes("application/json")) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      if (!response.ok) {
        let errorDetail = `Request failed with status ${response.status}`;
        if (data && typeof data === "object") {
          if (typeof data.detail === "string") {
            errorDetail = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorDetail = data.detail.map(d => d.msg || JSON.stringify(d)).join(", ");
          } else if (data.message) {
            errorDetail = data.message;
          }
        }
        throw new Error(errorDetail);
      }

      return data;
    } catch (error) {
      console.error(`API Error on ${endpoint}:`, error);
      throw error;
    }
  },

  // -------------------------------------------------------------
  // System Health & Diagnostics
  // -------------------------------------------------------------
  async getHealth() {
    try {
      const res = await fetch(`${API_BASE}/api/v1/health`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error("Health check failed:", err);
      return { status: "offline", error: err.message };
    }
  },

  // -------------------------------------------------------------
  // Authentication & Session
  // -------------------------------------------------------------
  async login(email, password) {
    const data = await this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (data.access_token) {
      this.setToken(data.access_token);
      this.setUser(data.user);
    }
    return data;
  },

  async getCurrentUser() {
    return await this.request("/api/v1/auth/me");
  },

  logout() {
    this.clearAuth();
    window.location.href = "/login";
  },

  getRedirectUrlForRole(role) {
    switch (role) {
      case "INSTITUTION":
        return "/institution";
      case "REGIONAL_OFFICER":
        return "/officer";
      case "BUREAU_OFFICER":
        return "/bureau";
      case "ADMIN":
        return "/admin";
      default:
        return "/";
    }
  },

  // -------------------------------------------------------------
  // Applications & Workflow Engine
  // -------------------------------------------------------------
  async getApplications(params = {}) {
    const query = new URLSearchParams();
    if (params.status) query.append("status", params.status);
    if (params.route_type) query.append("route_type", params.route_type);
    if (params.region) query.append("region", params.region);
    if (params.skip !== undefined) query.append("skip", params.skip);
    if (params.limit !== undefined) query.append("limit", params.limit);
    const qs = query.toString() ? `?${query.toString()}` : "";
    return await this.request(`/api/applications${qs}`);
  },

  async getApplication(id) {
    return await this.request(`/api/applications/${id}`);
  },

  async createApplication(payload) {
    return await this.request("/api/applications", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async completeStage(applicationId, payload = {}) {
    return await this.request(`/api/applications/${applicationId}/complete-stage`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async returnApplication(applicationId, reason) {
    return await this.request(`/api/applications/${applicationId}/return`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  // -------------------------------------------------------------
  // Expert Visit Committee (EVC)
  // -------------------------------------------------------------
  async getEVCQueue(params = {}) {
    const query = new URLSearchParams();
    if (params.status) query.append("status", params.status);
    if (params.region) query.append("region", params.region);
    if (params.visit_mode) query.append("visit_mode", params.visit_mode);
    if (params.skip !== undefined) query.append("skip", params.skip);
    if (params.limit !== undefined) query.append("limit", params.limit);
    const qs = query.toString() ? `?${query.toString()}` : "";
    return await this.request(`/api/evc${qs}`);
  },

  async getEVCVisit(visitId) {
    return await this.request(`/api/evc/${visitId}`);
  },

  async scheduleEVC(visitId, payload) {
    return await this.request(`/api/evc/${visitId}/schedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async rescheduleEVC(visitId, payload) {
    return await this.request(`/api/evc/${visitId}/reschedule`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async completeEVC(visitId, payload) {
    return await this.request(`/api/evc/${visitId}/complete`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async cancelEVC(visitId, reason) {
    return await this.request(`/api/evc/${visitId}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  // -------------------------------------------------------------
  // Statutory Undertakings & Compliance
  // -------------------------------------------------------------
  async getUndertakings(params = {}) {
    const query = new URLSearchParams();
    if (params.application_id) query.append("application_id", params.application_id);
    if (params.status) query.append("status", params.status);
    const qs = query.toString() ? `?${query.toString()}` : "";
    return await this.request(`/api/undertakings${qs}`);
  },

  async getUndertaking(id) {
    return await this.request(`/api/undertakings/${id}`);
  },

  async createUndertaking(payload) {
    return await this.request("/api/undertakings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async submitUndertakingEvidence(id, payload) {
    return await this.request(`/api/undertakings/${id}/submit-evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async verifyUndertaking(id, remarks = "") {
    return await this.request(`/api/undertakings/${id}/verify`, {
      method: "POST",
      body: JSON.stringify({ remarks: remarks || "Statutory compliance verified." }),
    });
  },

  async rejectUndertaking(id, rejection_reason, remarks = "") {
    return await this.request(`/api/undertakings/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ rejection_reason, remarks }),
    });
  },

  // -------------------------------------------------------------
  // Documents & Compliance Files
  // -------------------------------------------------------------
  async getDocuments(params = {}) {
    const query = new URLSearchParams();
    if (params.institution_id) query.append("institution_id", params.institution_id);
    if (params.application_id) query.append("application_id", params.application_id);
    if (params.doc_type) query.append("doc_type", params.doc_type);
    if (params.status) query.append("status", params.status);
    if (params.expiring_within_days) query.append("expiring_within_days", params.expiring_within_days);
    const qs = query.toString() ? `?${query.toString()}` : "";
    return await this.request(`/api/documents${qs}`);
  },

  async uploadDocument(formData) {
    return await this.request("/api/documents/upload", {
      method: "POST",
      body: formData,
    });
  },

  async verifyDocument(id, status = "VERIFIED", notes = "") {
    return await this.request(`/api/documents/${id}/verify`, {
      method: "POST",
      body: JSON.stringify({ status, verification_notes: notes }),
    });
  },

  // -------------------------------------------------------------
  // Notifications, Deadlines & Escalations
  // -------------------------------------------------------------
  async getNotifications(unreadOnly = false) {
    const qs = unreadOnly ? "?is_read=false" : "";
    return await this.request(`/api/notifications${qs}`);
  },

  async getUnreadNotificationCount() {
    return await this.request("/api/notifications/unread-count");
  },

  async markNotificationRead(id) {
    return await this.request(`/api/notifications/${id}/read`, {
      method: "POST",
    });
  },

  async markAllNotificationsRead() {
    return await this.request("/api/notifications/mark-all-read", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  async getEscalations() {
    return await this.request("/api/notifications/escalations");
  },

  async getDeadlineRules() {
    return await this.request("/api/notifications/rules");
  },

  async updateDeadlineRule(ruleId, payload) {
    return await this.request(`/api/notifications/rules/${ruleId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  async runDeadlineCheck() {
    return await this.request("/api/notifications/run-deadline-check", {
      method: "POST",
    });
  },

  // -------------------------------------------------------------
  // Administrator Demo Time Machine & Audit
  // -------------------------------------------------------------
  async getSimulatedTime() {
    return await this.request("/api/admin/simulated-time");
  },

  async advanceSimulatedTime(days, runDeadlineCheck = true) {
    return await this.request("/api/admin/advance-time", {
      method: "POST",
      body: JSON.stringify({ days, run_deadline_check: runDeadlineCheck }),
    });
  },

  async resetSimulatedTime() {
    return await this.request("/api/admin/reset-time", {
      method: "POST",
    });
  },

  async getAuditLogs(params = {}) {
    const query = new URLSearchParams();
    if (params.action) query.append("action", params.action);
    if (params.resource_type) query.append("resource_type", params.resource_type);
    if (params.skip !== undefined) query.append("skip", params.skip);
    if (params.limit !== undefined) query.append("limit", params.limit);
    const qs = query.toString() ? `?${query.toString()}` : "";
    return await this.request(`/api/admin/audit-logs${qs}`);
  },

  async getWorkflows() {
    return await this.request("/api/admin/workflows");
  },

  async getUsers() {
    return await this.request("/api/v1/users");
  },

  async createUser(payload) {
    return await this.request("/api/v1/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  // -------------------------------------------------------------
  // Security & Presentation Helpers
  // -------------------------------------------------------------
  escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  },

  formatDate(isoStr) {
    if (!isoStr) return "N/A";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoStr;
    }
  },

  formatDateOnly(isoStr) {
    if (!isoStr) return "N/A";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return isoStr;
    }
  },

  formatRelativeDays(isoStr) {
    if (!isoStr) return "";
    try {
      const target = new Date(isoStr);
      const now = new Date();
      const diffMs = target.getTime() - now.getTime();
      const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
      if (diffDays === 0) return "Today";
      if (diffDays > 0) return `In ${diffDays} day${diffDays > 1 ? "s" : ""}`;
      return `${Math.abs(diffDays)} day${Math.abs(diffDays) > 1 ? "s" : ""} overdue`;
    } catch {
      return "";
    }
  },

  showToast(message, type = "info") {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "fixed bottom-5 right-5 z-50 flex flex-col space-y-2 max-w-sm";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    let bg = "bg-slate-800 text-white border-slate-700";
    let icon = "ℹ️";
    if (type === "success") {
      bg = "bg-emerald-700 text-white border-emerald-600";
      icon = "✅";
    } else if (type === "error") {
      bg = "bg-red-700 text-white border-red-600";
      icon = "⚠️";
    } else if (type === "warning") {
      bg = "bg-amber-600 text-white border-amber-500";
      icon = "⏰";
    }

    toast.className = `${bg} px-4 py-3 rounded-lg shadow-lg border text-xs font-medium flex items-center justify-between space-x-3 transition-all duration-300 transform translate-y-2 opacity-0`;
    toast.innerHTML = `
      <div class="flex items-center space-x-2">
        <span>${icon}</span>
        <span>${this.escapeHtml(message)}</span>
      </div>
      <button class="text-white/70 hover:text-white font-bold ml-2 text-sm">&times;</button>
    `;

    toast.querySelector("button").onclick = () => {
      toast.remove();
    };

    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.remove("translate-y-2", "opacity-0");
    }, 10);

    setTimeout(() => {
      toast.classList.add("opacity-0", "translate-y-2");
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  },

  // -------------------------------------------------------------
  // Persistent Simulated Time Header Badge
  // -------------------------------------------------------------
  async initSimulatedTimeBadge() {
    const badgeEl = document.getElementById("simulated-time-badge");
    if (!badgeEl) return;

    try {
      const status = await this.getSimulatedTime();
      const simDate = status.simulated_date || (status.simulated_time ? status.simulated_time.slice(0, 10) : "");
      const realDate = status.real_date || (status.real_time ? status.real_time.slice(0, 10) : "");
      const isSim = status.offset_days > 0;

      if (isSim) {
        badgeEl.innerHTML = `
          <div class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-200 border border-amber-400/40">
            <span class="w-2 h-2 rounded-full bg-amber-400 mr-1.5 animate-pulse"></span>
            Simulated Date: ${simDate} (+${status.offset_days}d)
          </div>
        `;
        badgeEl.classList.remove("hidden");
      } else {
        badgeEl.innerHTML = `
          <div class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-white/10 text-slate-200 border border-white/20">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5"></span>
            Real Date: ${realDate}
          </div>
        `;
        badgeEl.classList.remove("hidden");
      }
    } catch (err) {
      console.warn("Could not load simulated time status:", err);
    }
  },

  // -------------------------------------------------------------
  // Shared In-App Notification Drawer
  // -------------------------------------------------------------
  async initNotificationDrawer() {
    const bellBtn = document.getElementById("btn-notification-bell");
    const countBadge = document.getElementById("notification-unread-count");
    const drawer = document.getElementById("notification-drawer");
    const listEl = document.getElementById("notification-drawer-list");
    const closeBtn = document.getElementById("btn-close-notifications");
    const markAllBtn = document.getElementById("btn-mark-all-read");

    if (!bellBtn || !drawer || !listEl) return;

    // Load unread count
    const updateCount = async () => {
      try {
        const res = await this.getUnreadNotificationCount();
        if (res.unread_count > 0) {
          countBadge.textContent = res.unread_count > 99 ? "99+" : res.unread_count;
          countBadge.classList.remove("hidden");
        } else {
          countBadge.classList.add("hidden");
        }
      } catch (err) {
        console.warn("Failed to update notification count:", err);
      }
    };

    const renderNotifications = async () => {
      listEl.innerHTML = `<div class="p-4 text-center text-xs text-slate-400">Loading notifications...</div>`;
      try {
        const notes = await this.getNotifications();
        if (!notes || notes.length === 0) {
          listEl.innerHTML = `
            <div class="p-8 text-center text-xs text-slate-400">
              <div class="text-3xl mb-2">🔔</div>
              No notifications yet.
            </div>`;
          return;
        }

        listEl.innerHTML = notes.map(n => {
          let typeClass = "bg-slate-50 border-slate-200";
          let badgeText = "INFO";
          let badgeColor = "bg-slate-100 text-slate-700";

          if (n.notification_type === "OVERDUE") {
            typeClass = "bg-red-50/50 border-red-200";
            badgeText = "OVERDUE";
            badgeColor = "bg-red-100 text-red-800";
          } else if (n.notification_type === "ESCALATION") {
            typeClass = "bg-purple-50/50 border-purple-200";
            badgeText = "ESCALATION";
            badgeColor = "bg-purple-100 text-purple-800";
          } else if (n.notification_type === "UPCOMING") {
            typeClass = "bg-amber-50/50 border-amber-200";
            badgeText = "REMINDER";
            badgeColor = "bg-amber-100 text-amber-800";
          }

          return `
            <div class="p-3 border-b text-xs ${typeClass} ${n.is_read ? 'opacity-70' : 'font-medium'} transition flex justify-between items-start gap-2" id="notif-item-${n.id}">
              <div class="flex-grow">
                <div class="flex items-center space-x-2 mb-1">
                  <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${badgeColor}">${badgeText}</span>
                  <span class="text-[10px] text-slate-400">${this.formatDate(n.created_at)}</span>
                </div>
                <p class="text-slate-800 leading-snug">${this.escapeHtml(n.message)}</p>
              </div>
              ${!n.is_read ? `
                <button onclick="API.markSingleRead(${n.id})" title="Mark as read" class="text-blue-700 hover:text-blue-900 text-xs px-1 py-0.5 rounded hover:bg-blue-100 transition whitespace-nowrap">
                  ✓ Read
                </button>
              ` : `
                <span class="text-slate-300 text-xs">✓</span>
              `}
            </div>
          `;
        }).join("");
      } catch (err) {
        listEl.innerHTML = `<div class="p-4 text-center text-xs text-red-500">Failed to load notifications: ${this.escapeHtml(err.message)}</div>`;
      }
    };

    bellBtn.onclick = () => {
      drawer.classList.remove("hidden");
      renderNotifications();
    };

    if (closeBtn) {
      closeBtn.onclick = () => {
        drawer.classList.add("hidden");
      };
    }

    if (markAllBtn) {
      markAllBtn.onclick = async () => {
        try {
          await this.markAllNotificationsRead();
          this.showToast("All notifications marked as read", "success");
          await updateCount();
          renderNotifications();
        } catch (err) {
          this.showToast(err.message || "Failed to mark all as read", "error");
        }
      };
    }

    this.markSingleRead = async (id) => {
      try {
        await this.markNotificationRead(id);
        await updateCount();
        const item = document.getElementById(`notif-item-${id}`);
        if (item) {
          item.classList.add("opacity-70");
          item.classList.remove("font-medium");
          const btn = item.querySelector("button");
          if (btn) btn.outerHTML = `<span class="text-slate-300 text-xs">✓</span>`;
        }
      } catch (err) {
        this.showToast(err.message || "Failed to mark read", "error");
      }
    };

    // Initial count fetch
    updateCount();
  }
};

window.API = API;
