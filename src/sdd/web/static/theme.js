// Theme: dark unless the user chose light with the toggle, or has never toggled and the system
// prefers light. The choice is per browser (localStorage, which may be blocked).
const root = document.documentElement;
const KEY = "sdd-theme";

function saved() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "";
  } catch {
    return "";
  }
}

const systemLight = () => matchMedia("(prefers-color-scheme: light)").matches;

export function currentTheme() {
  return saved() || (systemLight() ? "light" : "dark");
}

export function applyTheme() {
  root.dataset.theme = currentTheme();
  return root.dataset.theme;
}

export function toggleTheme() {
  const next = root.dataset.theme === "light" ? "dark" : "light";
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* storage blocked: the choice lasts until reload */
  }
  root.dataset.theme = next;
  window.dispatchEvent(new Event("themechange"));
  return next;
}

// Until the toggle is used, follow the system.
matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
  if (saved()) return;
  applyTheme();
  window.dispatchEvent(new Event("themechange"));
});

applyTheme();
