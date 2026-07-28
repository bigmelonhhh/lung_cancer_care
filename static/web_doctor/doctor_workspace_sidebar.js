(function () {
  "use strict";

  const STORAGE_KEY = "lcc:doctor-workspace:left-sidebar-collapsed:v1";
  const TRANSITION_FALLBACK_MS = 250;
  const sidebar = document.getElementById("doctor-patient-sidebar");
  const content = document.getElementById("doctor-patient-sidebar-content");
  const toggle = document.getElementById("doctor-patient-sidebar-toggle");

  if (!sidebar || !content || !toggle) return;

  const collapseIcon = toggle.querySelector("[data-sidebar-collapse-icon]");
  const expandIcon = toggle.querySelector("[data-sidebar-expand-icon]");
  const toggleLabel = toggle.querySelector("[data-sidebar-toggle-label]");
  let layoutTimer = null;

  const readStoredState = function () {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch (error) {
      return false;
    }
  };

  const storeState = function (collapsed) {
    try {
      window.localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    } catch (error) {}
  };

  const setElementHidden = function (element, hidden) {
    if (!element) return;
    element.toggleAttribute("hidden", hidden);
    element.classList.toggle("hidden", hidden);
  };

  const notifyLayoutListeners = function () {
    if (layoutTimer !== null) {
      window.clearTimeout(layoutTimer);
      layoutTimer = null;
    }
    window.dispatchEvent(new Event("resize"));
  };

  const scheduleLayoutNotification = function () {
    if (layoutTimer !== null) window.clearTimeout(layoutTimer);
    layoutTimer = window.setTimeout(notifyLayoutListeners, TRANSITION_FALLBACK_MS);
  };

  const applyState = function (collapsed, persist) {
    const expanded = !collapsed;
    const label = expanded ? "收起患者菜单" : "展开患者菜单";

    sidebar.dataset.collapsed = collapsed ? "true" : "false";
    setElementHidden(content, collapsed);
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
    if (toggleLabel) toggleLabel.textContent = label;
    setElementHidden(collapseIcon, collapsed);
    setElementHidden(expandIcon, !collapsed);

    if (persist) {
      storeState(collapsed);
      scheduleLayoutNotification();
    }
  };

  sidebar.addEventListener("transitionend", function (event) {
    if (event.target !== sidebar || event.propertyName !== "width") return;
    notifyLayoutListeners();
  });

  toggle.addEventListener("click", function () {
    applyState(sidebar.dataset.collapsed !== "true", true);
  });

  applyState(readStoredState(), false);
})();
