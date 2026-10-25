/**
 * AICTE Platform Global App Shell
 */
document.addEventListener("DOMContentLoaded", async () => {
  const statusBadge = document.getElementById("backend-status-badge");
  const envText = document.getElementById("backend-env-text");

  if (statusBadge && window.API) {
    const health = await window.API.getHealth();
    if (health.status === "healthy") {
      statusBadge.textContent = "API: Online (Healthy)";
      statusBadge.className = "px-3 py-1 text-xs font-semibold rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300";
    } else {
      statusBadge.textContent = `API: ${health.status || "Degraded"}`;
      statusBadge.className = "px-3 py-1 text-xs font-semibold rounded-full bg-amber-100 text-amber-800 border border-amber-300";
    }
    if (envText && health.app_env) {
      envText.textContent = `Environment: ${health.app_env.toUpperCase()}`;
    }
  }
});
