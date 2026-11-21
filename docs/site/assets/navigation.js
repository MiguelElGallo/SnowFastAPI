// Zensical's compact navigation uses a checkbox. Keep its visual and keyboard states in sync.
function enableCompactNavigation() {
  const drawer = document.querySelector("#__drawer");
  const label = document.querySelector('.md-header label[for="__drawer"]');
  const sidebar = document.querySelector(".md-sidebar--primary");
  const list = sidebar?.querySelector(".md-nav--primary > .md-nav__list");
  if (!drawer || !label || !sidebar || !list) return;

  const compact = window.matchMedia("(max-width: 76.234375em)");
  const open = document.createElement("button");
  open.type = "button";
  open.className = label.className + " sf-nav-trigger";
  open.setAttribute("aria-label", "Open navigation");
  sidebar.id ||= "sf-navigation";
  open.setAttribute("aria-controls", sidebar.id);
  const icon = label.querySelector("svg")?.cloneNode(true);
  if (icon) {
    icon.setAttribute("aria-hidden", "true");
    open.append(icon);
  }
  label.after(open);
  label.hidden = true;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "sf-nav-close";
  close.textContent = "Close navigation";
  list.before(close);

  function sync() {
    const expanded = compact.matches && drawer.checked;
    open.setAttribute("aria-expanded", String(expanded));
    sidebar.inert = compact.matches && !expanded;
  }
  open.addEventListener("click", () => drawer.click());
  close.addEventListener("click", () => drawer.click());
  drawer.addEventListener("change", () => {
    sync();
    if (compact.matches) (drawer.checked ? close : open).focus({ preventScroll: true });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && compact.matches && drawer.checked) {
      event.preventDefault();
      drawer.click();
    }
  });
  compact.addEventListener("change", sync);
  sync();

  const search = document.querySelector('.md-header label[for="__search"]');
  if (search) {
    search.tabIndex = 0;
    search.setAttribute("role", "button");
    search.setAttribute("aria-label", "Search documentation");
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        search.click();
      }
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", enableCompactNavigation, { once: true });
} else {
  enableCompactNavigation();
}
