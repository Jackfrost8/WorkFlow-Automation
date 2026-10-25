/**
 * AICTE Centralized API Client
 */
const API_BASE = window.location.origin;

const API = {
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

  async request(endpoint, options = {}) {
    const defaultHeaders = {
      "Content-Type": "application/json",
      "Accept": "application/json",
    };

    // Attach token if present
    const token = localStorage.getItem("aicte_token");
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
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `Request failed with status ${response.status}`);
      }
      return data;
    } catch (error) {
      console.error(`API Error on ${endpoint}:`, error);
      throw error;
    }
  }
};

window.API = API;
