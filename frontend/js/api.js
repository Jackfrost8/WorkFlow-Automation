/**
 * AICTE Centralized API Client with JWT Authentication & Error Interception
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
      "Content-Type": "application/json",
      "Accept": "application/json",
    };

    const token = this.getToken();
    if (token) {
      defaultHeaders["Authorization"] = `Bearer ${token}`;
    }

    const config = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
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
        const errorDetail = (data && data.detail) || `Request failed with status ${response.status}`;
        throw new Error(errorDetail);
      }

      return data;
    } catch (error) {
      console.error(`API Error on ${endpoint}:`, error);
      throw error;
    }
  },

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
      case "BUREAU_OFFICER":
        return "/officer";
      case "ADMIN":
        return "/admin";
      default:
        return "/";
    }
  }
};

window.API = API;
