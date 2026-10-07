/* OrionFlow — shared page behaviour: navigation, reveal-on-scroll, Book a Demo.
   Plain ES5 so it runs everywhere without a build step. */
(function () {
  "use strict";

  // ---- configuration --------------------------------------------------------
  var CONTACT_EMAIL = "sahilmaniyar@orionflow.in";
  // Google Calendar appointment schedule: the embed shows live availability and
  // books straight into the calendar; the short link is the same page full-size.
  var BOOKING_EMBED = "https://calendar.google.com/calendar/appointments/schedules/AcZssZ0lxnCHeNhVeCeLrP8TvwMfV0mP_ZxhJkPIzaXtXTSWd_ILyBla_otcmG5DH5S9jH2p_IHkKTT-?gv=true";
  var BOOKING_URL = "https://calendar.app.google/2oyA7iL2iKjQPf9u6";

  var doc = document;
  function $(sel, root) { return (root || doc).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

  // ---- navigation -----------------------------------------------------------
  var nav = $(".nav");
  if (nav) {
    var onScroll = function () { nav.classList.toggle("is-scrolled", window.scrollY > 8); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    var menuBtn = $(".nav__menu"), sheet = $(".sheet-menu");
    if (menuBtn && sheet) {
      var setOpen = function (open) {
        nav.classList.toggle("is-open", open);
        sheet.hidden = !open;
        menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
      };
      menuBtn.addEventListener("click", function () { setOpen(sheet.hidden); });
      $$("a", sheet).forEach(function (a) { a.addEventListener("click", function () { setOpen(false); }); });
    }
  }

  // ---- reveal on scroll -----------------------------------------------------
  var rv = $$(".rv, .prod__card");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: 0.18, rootMargin: "0px 0px -40px 0px" });
    rv.forEach(function (n) { io.observe(n); });
  } else {
    rv.forEach(function (n) { n.classList.add("in"); });
  }
  // stroke lengths for the line drawings that draw themselves in
  $$(".prod__fig .dr").forEach(function (p) {
    try { p.style.setProperty("--len", Math.ceil(p.getTotalLength()) + 1); } catch (e) {}
  });

  var year = $("#year");
  if (year) year.textContent = new Date().getFullYear();

  // ---- Book a Demo: Google appointment schedule in a dialog ------------------
  var dialog = null;

  function build() {
    dialog = doc.createElement("dialog");
    dialog.className = "demo";
    dialog.setAttribute("aria-labelledby", "demo-title");
    dialog.innerHTML =
      '<div class="demo__head"><div><span class="label">Book a demo · 30 min</span>' +
      '<h2 id="demo-title">See OrionFlow on your parts.</h2>' +
      "<p>Pick a time that works. You'll get a calendar invite with a video link straight away.</p></div>" +
      '<button class="demo__x" type="button" aria-label="Close" data-close>×</button></div>' +
      '<div class="demo__cal"><div class="demo__load"><span class="spin" aria-hidden="true"></span>&nbsp; Loading availability…</div>' +
      '<iframe title="Book a demo with OrionFlow" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe></div>' +
      '<div class="demo__foot"><p>Calendar not loading? <a class="link" href="' + BOOKING_URL +
      '" target="_blank" rel="noopener">Open the booking page ↗</a></p>' +
      '<a class="link" href="mailto:' + CONTACT_EMAIL + '?subject=' + encodeURIComponent("OrionFlow demo") + '">' + CONTACT_EMAIL + "</a></div>";
    doc.body.appendChild(dialog);
    var frame = $("iframe", dialog);
    frame.addEventListener("load", function () { dialog.classList.add("is-loaded"); });
    frame.src = BOOKING_EMBED;
    $$("[data-close]", dialog).forEach(function (b) { b.addEventListener("click", close); });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) close(); });
    dialog.addEventListener("close", function () { doc.documentElement.style.overflow = ""; });
  }

  function open() {
    if (!dialog) build();
    if (dialog.open) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else { window.open(BOOKING_URL, "_blank", "noopener"); return; }
    doc.documentElement.style.overflow = "hidden";
  }
  function close() {
    if (!dialog) return;
    if (dialog.open) dialog.close();
    doc.documentElement.style.overflow = "";
    if (location.hash === "#demo") history.replaceState(null, "", location.pathname + location.search);
  }

  doc.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-demo]");
    if (!t || e.metaKey || e.ctrlKey || e.shiftKey) return;   // modified click: let the link open the page
    e.preventDefault();
    open();
  });
  if (location.hash === "#demo") open();
  window.addEventListener("hashchange", function () { if (location.hash === "#demo") open(); });
})();
