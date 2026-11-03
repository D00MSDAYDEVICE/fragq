// Loaded in <head> so the saved theme applies before first paint.
(function () {
  var t = null;
  try { t = localStorage.getItem("fragq-theme"); } catch (e) { /* storage blocked */ }
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
})();
