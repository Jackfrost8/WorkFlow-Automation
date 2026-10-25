/**
 * AICTE Authentication Guard & Session Management
 */
document.addEventListener("DOMContentLoaded", async () => {
  const currentPath = window.location.pathname;

  // Pages that require authentication
  const protectedRoutes = {
    "/institution": ["INSTITUTION"],
    "/officer": ["REGIONAL_OFFICER", "BUREAU_OFFICER"],
    "/admin": ["ADMIN"],
  };

  const allowedRoles = protectedRoutes[currentPath];

  // If this is a protected page
  if (allowedRoles) {
    const token = window.API.getToken();
    const user = window.API.getUser();

    if (!token || !user) {
      window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`;
      return;
    }

    // Role verification
    if (!allowedRoles.includes(user.role)) {
      console.warn(`Unauthorized access attempt to ${currentPath} by role ${user.role}`);
      const correctUrl = window.API.getRedirectUrlForRole(user.role);
      window.location.href = correctUrl;
      return;
    }

    // Update UI headers with current user info
    renderUserNavProfile(user);
  }

  // Setup logout buttons
  const logoutButtons = document.querySelectorAll(".btn-logout");
  logoutButtons.forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      window.API.logout();
    });
  });
});

function renderUserNavProfile(user) {
  const nameEl = document.getElementById("nav-user-name");
  const roleEl = document.getElementById("nav-user-role");
  const emailEl = document.getElementById("nav-user-email");
  const regionEl = document.getElementById("nav-user-region");

  if (nameEl) nameEl.textContent = user.full_name;
  if (roleEl) roleEl.textContent = user.role.replace("_", " ");
  if (emailEl) emailEl.textContent = user.email;
  if (regionEl && user.region) regionEl.textContent = user.region;
}
