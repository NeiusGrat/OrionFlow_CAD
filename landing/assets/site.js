/* OrionFlow — shared page behaviour: navigation, reveal-on-scroll, Book a demo + Sign in.
   Plain ES5 so it runs everywhere without a build step. */
(function () {
  "use strict";

  // ---- configuration --------------------------------------------------------
  var CONTACT_EMAIL = "sahilmaniyar@orionflow.in";
  // Google Calendar appointment schedule: the embed shows live availability and
  // books straight into the calendar; the short link is the same page full-size.
  var BOOKING_EMBED = "https://calendar.google.com/calendar/appointments/schedules/AcZssZ0lxnCHeNhVeCeLrP8TvwMfV0mP_ZxhJkPIzaXtXTSWd_ILyBla_otcmG5DH5S9jH2p_IHkKTT-?gv=true";
  var BOOKING_URL = "https://calendar.app.google/2oyA7iL2iKjQPf9u6";
  var API = "https://sahilmaniyar57--orionflow-api-api.modal.run";
  var APP = "https://app.orionflow.in";

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

  // ---- dialogs: Book a demo + Sign in ---------------------------------------
  // Both are real forms against the API. Book a demo stores the request first
  // (so a visitor who never picks a slot is still a lead), then offers the
  // calendar. Sign in authenticates here and hands the session to the app.
  function esc(t) {
    return String(t).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var warmed = false;
  function warm() {               // the API scales to zero; wake it while they type
    if (warmed) return;
    warmed = true;
    try { fetch(API + "/health", { mode: "cors" }).catch(function () {}); } catch (e) {}
  }

  function errorText(body, fallback) {
    if (!body) return fallback;
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && body.detail[0] && body.detail[0].msg) {
      var d = body.detail[0], f = d.loc && d.loc[d.loc.length - 1];
      return (f ? f.charAt(0).toUpperCase() + f.slice(1) + ": " : "") + d.msg;
    }
    if (body.error && body.error.message) return body.error.message;
    return fallback;
  }

  // POST with a "waking up" hint after 3 s and one clear error path.
  function submit(form, url, init, onOk) {
    var btn = $("button[type=submit]", form), msg = $(".fm__msg", form), label = btn.innerHTML;
    msg.textContent = ""; msg.className = "fm__msg";
    btn.disabled = true;
    btn.innerHTML = '<span class="spin" aria-hidden="true"></span>&nbsp; Working…';
    var slow = setTimeout(function () { msg.textContent = "Waking the server up — a few more seconds…"; }, 3000);
    function done() { clearTimeout(slow); btn.disabled = false; btn.innerHTML = label; }
    fetch(url, init).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        done();
        if (res.ok) { msg.textContent = ""; onOk(body); return; }
        var fallback = res.status === 429 ? "Too many attempts. Wait a minute and try again."
          : "Something went wrong (" + res.status + "). Please try again.";
        msg.className = "fm__msg is-err";
        msg.textContent = errorText(body, fallback);
      });
    }).catch(function () {
      done();
      msg.className = "fm__msg is-err";
      msg.textContent = "Couldn't reach OrionFlow. Check your connection and try again.";
    });
  }

  function makeDialog(cls, labelledby, html) {
    var d = doc.createElement("dialog");
    d.className = "demo " + cls;
    d.setAttribute("aria-labelledby", labelledby);
    d.innerHTML = html;
    doc.body.appendChild(d);
    function close() { if (d.open) d.close(); }
    $$("[data-close]", d).forEach(function (b) { b.addEventListener("click", close); });
    d.addEventListener("click", function (e) { if (e.target === d) close(); });
    d.addEventListener("close", function () {
      doc.documentElement.style.overflow = "";
      if (location.hash === "#demo" || location.hash === "#signin") {
        history.replaceState(null, "", location.pathname + location.search);
      }
    });
    return d;
  }
  function show(d, fallbackUrl) {
    if (d.open) return;
    $$("dialog.demo[open]").forEach(function (o) { o.close(); });
    if (typeof d.showModal !== "function") { location.href = fallbackUrl; return; }
    d.showModal();
    doc.documentElement.style.overflow = "hidden";
    var first = $("input:not(.fm__hp)", d);
    if (first && !first.closest("[hidden]") && window.matchMedia("(min-width: 601px)").matches) first.focus();
  }
  var X = '<button class="demo__x" type="button" aria-label="Close" data-close>×</button>';
  var HP = '<input class="fm__hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">';
  var MAIL = '<a class="link" href="mailto:' + CONTACT_EMAIL + '?subject=' +
    encodeURIComponent("OrionFlow demo") + '">' + CONTACT_EMAIL + "</a>";
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  // -- Book a demo ------------------------------------------------------------
  var demo = null;
  function buildDemo() {
    demo = makeDialog("demo--form", "demo-title",
      '<div class="demo__head"><div><span class="label">Book a demo · 30 min</span>' +
      '<h2 id="demo-title">See OrionFlow on your parts.</h2>' +
      "<p>Tell us a little about your team, then pick a time.</p></div>" + X + "</div>" +
      '<form class="fm" novalidate>' +
      '<div class="fm__row"><label class="fm__f"><span>Full name</span><input name="name" required maxlength="200" autocomplete="name"></label>' +
      '<label class="fm__f"><span>Work email</span><input name="email" type="email" required maxlength="320" autocomplete="email"></label></div>' +
      '<div class="fm__row"><label class="fm__f"><span>Company</span><input name="company" required maxlength="200" autocomplete="organization"></label>' +
      '<label class="fm__f"><span>Role <em>optional</em></span><input name="role" maxlength="200" autocomplete="organization-title"></label></div>' +
      '<label class="fm__f"><span>What would you like to see? <em>optional</em></span>' +
      '<textarea name="message" rows="3" maxlength="4000" placeholder="e.g. drawing checks on supplier parts, FAI reports, robot CAD review"></textarea></label>' +
      HP +
      '<p class="fm__msg" role="status" aria-live="polite"></p>' +
      '<div class="fm__act"><button class="btn" type="submit">Continue to pick a time <span class="arr">→</span></button>' + MAIL + "</div>" +
      "</form>" +
      '<div class="demo__cal" hidden><div class="demo__load"><span class="spin" aria-hidden="true"></span>&nbsp; Loading availability…</div>' +
      '<iframe title="Book a demo with OrionFlow" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe></div>' +
      '<div class="demo__foot" hidden><p>Calendar not loading? <a class="link" href="' + BOOKING_URL +
      '" target="_blank" rel="noopener">Open the booking page ↗</a></p>' + MAIL + "</div>");

    var form = $("form", demo);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = form.elements, msg = $(".fm__msg", form);
      var data = {
        name: f.name.value.trim(), email: f.email.value.trim(), company: f.company.value.trim(),
        role: f.role.value.trim(), message: f.message.value.trim(), website: f.website.value,
        source: ("landing:" + (location.pathname || "/")).slice(0, 64)
      };
      var bad = !data.name ? f.name : !EMAIL_RE.test(data.email) ? f.email : !data.company ? f.company : null;
      if (bad) {
        msg.className = "fm__msg is-err";
        msg.textContent = bad === f.email ? "Enter a valid work email." : "Please fill in your " + bad.name + ".";
        bad.focus();
        return;
      }
      submit(form, API + "/api/v1/demo-requests", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data)
      }, function () {
        $("#demo-title", demo).textContent = "Thanks, " + data.name.split(" ")[0] + ". Now pick a time.";
        $(".demo__head p", demo).innerHTML = "We've got your request (" + esc(data.email) +
          "). Choose a slot and you'll get a calendar invite with a video link.";
        form.hidden = true;
        demo.classList.remove("demo--form");
        $(".demo__cal", demo).hidden = false;
        $(".demo__foot", demo).hidden = false;
        var frame = $("iframe", demo);
        frame.addEventListener("load", function () { demo.classList.add("is-loaded"); });
        frame.src = BOOKING_EMBED;
      });
    });
  }
  function openDemo() { warm(); if (!demo) buildDemo(); show(demo, BOOKING_URL); }

  // -- Sign in ----------------------------------------------------------------
  var signin = null;
  function buildSignin() {
    signin = makeDialog("demo--form demo--narrow", "signin-title",
      '<div class="demo__head"><div><span class="label">OrionFlow</span>' +
      '<h2 id="signin-title">Sign in to continue.</h2></div>' + X + "</div>" +
      '<form class="fm" novalidate>' +
      '<label class="fm__f"><span>Email</span><input name="email" type="email" required autocomplete="username"></label>' +
      '<label class="fm__f"><span>Password <a class="fm__aside" href="' + APP + '/auth/forgot-password">Forgot?</a></span>' +
      '<input name="password" type="password" required autocomplete="current-password"></label>' +
      '<p class="fm__msg" role="status" aria-live="polite"></p>' +
      '<button class="btn fm__wide" type="submit">Sign in <span class="arr">→</span></button>' +
      '<div class="fm__or"><span>or</span></div>' +
      '<a class="btn btn--ghost fm__wide" href="' + APP + '/auth">Continue with Google</a>' +
      '<p class="fm__note">New to OrionFlow? <a href="' + APP + '/auth?intent=signup">Create an account</a></p>' +
      "</form>");

    var form = $("form", signin);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var f = form.elements, msg = $(".fm__msg", form);
      var email = f.email.value.trim(), password = f.password.value;
      if (!EMAIL_RE.test(email) || !password) {
        msg.className = "fm__msg is-err";
        msg.textContent = !EMAIL_RE.test(email) ? "Enter a valid email." : "Enter your password.";
        (EMAIL_RE.test(email) ? f.password : f.email).focus();
        return;
      }
      submit(form, API + "/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "username=" + encodeURIComponent(email) + "&password=" + encodeURIComponent(password)
      }, function (tok) {
        $(".fm__msg", form).textContent = "Signed in — opening OrionFlow…";
        // Tokens travel in the fragment, which never reaches a server; the app
        // strips it from history before using it.
        location.href = APP + "/auth/handoff#access_token=" + encodeURIComponent(tok.access_token) +
          "&refresh_token=" + encodeURIComponent(tok.refresh_token);
      });
    });
  }
  function openSignin() { warm(); if (!signin) buildSignin(); show(signin, APP + "/auth"); }

  doc.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-demo],[data-signin]");
    if (!t || e.metaKey || e.ctrlKey || e.shiftKey) return;   // modified click: let the link open the page
    e.preventDefault();
    if (t.hasAttribute("data-signin")) openSignin(); else openDemo();
  });
  function fromHash() {
    if (location.hash === "#demo") openDemo();
    else if (location.hash === "#signin") openSignin();
  }
  fromHash();
  window.addEventListener("hashchange", fromHash);
})();
