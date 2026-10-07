/* OrionFlow hero — hardware as point clouds.
   Four objects are sampled from simple solids (boxes, cylinders, cones,
   ellipsoids, plates) into the same number of surface points, then the cloud
   dissolves from one into the next: F1 car → humanoid → launch vehicle → gear.
   Canvas 2D, no dependencies. */
(function () {
  "use strict";
  var canvas = document.getElementById("cloud");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var small = window.innerWidth < 700;
  var N = small ? 2000 : 3400;
  var HOLD = 5600, MORPH = 2200;

  // ---- seeded random so every load draws the same objects ------------------
  var seed = 7;
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
  function rr(a, b) { return a + (b - a) * rnd(); }
  var WIRE = 0.42;                              // share of points placed on edges

  // ---- surface samplers: {a: area, s: () => [x,y,z]} ------------------------
  function box(cx, cy, cz, sx, sy, sz) {
    var axy = sx * sy, ayz = sy * sz, axz = sx * sz, A = 2 * (axy + ayz + axz);
    return { a: A, s: function () {
      var r = rnd() * (axy + ayz + axz), sg = rnd() < 0.5 ? -0.5 : 0.5;
      var x = rr(-0.5, 0.5) * sx, y = rr(-0.5, 0.5) * sy, z = rr(-0.5, 0.5) * sz;
      if (rnd() < WIRE) {                       // on one of the 12 edges
        var e = rnd() * (sx + sy + sz), a = rnd() < 0.5 ? -0.5 : 0.5, b = rnd() < 0.5 ? -0.5 : 0.5;
        if (e < sx) { y = a * sy; z = b * sz; } else if (e < sx + sy) { x = a * sx; z = b * sz; } else { x = a * sx; y = b * sy; }
        return [cx + x, cy + y, cz + z];
      }
      if (r < axy) z = sg * sz; else if (r < axy + ayz) x = sg * sx; else y = sg * sy;
      return [cx + x, cy + y, cz + z];
    } };
  }
  function orient(axis, u, v, w) {            // u,v radial, w along axis
    return axis === "x" ? [w, u, v] : axis === "y" ? [u, w, v] : [u, v, w];
  }
  function cyl(c, r, L, axis, caps) {
    var side = 2 * Math.PI * r * L, cap = caps === false ? 0 : Math.PI * r * r;
    return { a: side + 2 * cap, s: function () {
      var t = rnd() * (side + 2 * cap), th = rr(0, 2 * Math.PI), rad = r, w;
      if (rnd() < WIRE) w = rnd() < 0.5 ? -L / 2 : L / 2;
      else if (t < side) w = rr(-L / 2, L / 2);
      else { w = t < side + cap ? -L / 2 : L / 2; rad = r * Math.sqrt(rnd()); }
      var p = orient(axis, rad * Math.cos(th), rad * Math.sin(th), w);
      return [c[0] + p[0], c[1] + p[1], c[2] + p[2]];
    } };
  }
  function frustum(c, r0, r1, L, axis) {        // r0 at -L/2, r1 at +L/2, open
    var A = Math.PI * (r0 + r1) * Math.sqrt(L * L + (r1 - r0) * (r1 - r0));
    var rm = Math.max(r0, r1);
    return { a: A, s: function () {
      var t, rad;
      if (rnd() < WIRE * 0.7) { t = rnd() < 0.5 ? 0 : 1; rad = r0 + (r1 - r0) * t; }
      else do { t = rnd(); rad = r0 + (r1 - r0) * t; } while (rnd() * rm > rad);
      var th = rr(0, 2 * Math.PI);
      var p = orient(axis, rad * Math.cos(th), rad * Math.sin(th), (t - 0.5) * L);
      return [c[0] + p[0], c[1] + p[1], c[2] + p[2]];
    } };
  }
  function ellip(c, rx, ry, rz, yCut) {         // yCut: keep only y >= c.y + yCut*ry
    var p = 1.6, A = 4 * Math.PI * Math.pow((Math.pow(rx * ry, p) + Math.pow(rx * rz, p) + Math.pow(ry * rz, p)) / 3, 1 / p);
    if (yCut != null) A *= (1 - yCut) / 2;
    return { a: A, s: function () {
      var x, y, z, d;
      if (rnd() < WIRE * 0.45) {                // an equator or meridian ring
        var th = rr(0, 2 * Math.PI), ring = rnd();
        if (ring < 0.5) { x = Math.cos(th); y = 0; z = Math.sin(th); }
        else { x = Math.cos(th) * (ring < 0.75 ? 1 : 0); z = Math.cos(th) * (ring < 0.75 ? 0 : 1); y = Math.sin(th); }
        if (yCut == null || y >= yCut) return [c[0] + rx * x, c[1] + ry * y, c[2] + rz * z];
      }
      do {
        x = rr(-1, 1); y = rr(-1, 1); z = rr(-1, 1); d = Math.sqrt(x * x + y * y + z * z);
      } while (d > 1 || d < 0.05 || (yCut != null && y / d < yCut));
      return [c[0] + rx * x / d, c[1] + ry * y / d, c[2] + rz * z / d];
    } };
  }
  function tri(a, b, c, th) {                   // a thin plate: both faces
    var ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    var cr = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]];
    var len = Math.sqrt(cr[0] * cr[0] + cr[1] * cr[1] + cr[2] * cr[2]) || 1;
    var n = [cr[0] / len, cr[1] / len, cr[2] / len];
    return { a: len, s: function () {
      var u = rnd(), v = rnd();
      if (u + v > 1) { u = 1 - u; v = 1 - v; }
      var o = (rnd() < 0.5 ? -0.5 : 0.5) * th;
      return [a[0] + ab[0] * u + ac[0] * v + n[0] * o, a[1] + ab[1] * u + ac[1] * v + n[1] * o, a[2] + ab[2] * u + ac[2] * v + n[2] * o];
    } };
  }
  function tube(pts, r) {                       // thin rod along a polyline
    var segs = [], L = 0;
    for (var i = 0; i < pts.length - 1; i++) {
      var a = pts[i], b = pts[i + 1], l = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
      segs.push([a, b, l]); L += l;
    }
    return { a: 2 * Math.PI * r * L, s: function () {
      var t = rnd() * L, k = 0;
      while (k < segs.length - 1 && t > segs[k][2]) { t -= segs[k][2]; k++; }
      var s = segs[k], f = t / s[2];
      return [s[0][0] + (s[1][0] - s[0][0]) * f + rr(-r, r), s[0][1] + (s[1][1] - s[0][1]) * f + rr(-r, r), s[0][2] + (s[1][2] - s[0][2]) * f + rr(-r, r)];
    } };
  }
  function gear(c, teeth, Ro, Ri, bore, t, holes, holeR, holePitch) {
    function prof(phi) {                        // trapezoid teeth
      var u = ((phi / (2 * Math.PI)) * teeth) % 1;
      if (u < 0.18) return Ri + (Ro - Ri) * (u / 0.18);
      if (u < 0.5) return Ro;
      if (u < 0.68) return Ro - (Ro - Ri) * ((u - 0.5) / 0.18);
      return Ri;
    }
    function inHole(x, z) {
      for (var k = 0; k < holes; k++) {
        var a = (k / holes) * 2 * Math.PI, hx = holePitch * Math.cos(a), hz = holePitch * Math.sin(a);
        if ((x - hx) * (x - hx) + (z - hz) * (z - hz) < holeR * holeR) return true;
      }
      return false;
    }
    var face = Math.PI * (Ro * Ro - bore * bore), rim = 2 * Math.PI * Ro * t * 1.6, bw = 2 * Math.PI * bore * t, hw = holes * 2 * Math.PI * holeR * t;
    return { a: 2 * face + rim + bw + hw, s: function () {
      var r = rnd() * (2 * face + rim + bw + hw), x, y, z, phi, rad;
      if (rnd() < WIRE) {                       // tooth profile + bore edges on both faces
        phi = rr(0, 2 * Math.PI); y = rnd() < 0.5 ? -t / 2 : t / 2;
        var q = rnd(); rad = q < 0.7 ? prof(phi) : bore;
        if (q >= 0.85) {
          var kk = Math.floor(rnd() * holes), aa = (kk / holes) * 2 * Math.PI;
          return [c[0] + holePitch * Math.cos(aa) + holeR * Math.cos(phi), c[1] + y, c[2] + holePitch * Math.sin(aa) + holeR * Math.sin(phi)];
        }
        return [c[0] + rad * Math.cos(phi), c[1] + y, c[2] + rad * Math.sin(phi)];
      }
      if (r < 2 * face) {
        do { phi = rr(0, 2 * Math.PI); rad = Math.sqrt(rr(bore * bore, Ro * Ro)); x = rad * Math.cos(phi); z = rad * Math.sin(phi); }
        while (rad > prof(phi) || inHole(x, z));
        y = r < face ? -t / 2 : t / 2;
      } else if (r < 2 * face + rim) {
        phi = rr(0, 2 * Math.PI); rad = prof(phi); x = rad * Math.cos(phi); z = rad * Math.sin(phi); y = rr(-t / 2, t / 2);
      } else if (r < 2 * face + rim + bw) {
        phi = rr(0, 2 * Math.PI); x = bore * Math.cos(phi); z = bore * Math.sin(phi); y = rr(-t / 2, t / 2);
      } else {
        var k = Math.floor(rnd() * holes), a = (k / holes) * 2 * Math.PI;
        phi = rr(0, 2 * Math.PI);
        x = holePitch * Math.cos(a) + holeR * Math.cos(phi); z = holePitch * Math.sin(a) + holeR * Math.sin(phi); y = rr(-t / 2, t / 2);
      }
      return [c[0] + x, c[1] + y, c[2] + z];
    } };
  }

  // ---- the four objects (x = length, y = up, z = width) --------------------
  function f1() {
    var p = [], wy = 0.17;
    p.push(frustum([-0.67, 0.19, 0], 0.035, 0.12, 0.66, "x"));          // nose
    p.push(box(0.02, 0.2, 0, 0.74, 0.2, 0.3));                          // monocoque
    p.push(box(0.16, 0.18, 0.25, 0.52, 0.16, 0.2));                     // sidepods
    p.push(box(0.16, 0.18, -0.25, 0.52, 0.16, 0.2));
    p.push(frustum([0.4, 0.33, 0], 0.13, 0.05, 0.75, "x"));             // engine cover
    p.push(ellip([0.02, 0.4, 0], 0.09, 0.11, 0.08, -0.1));              // airbox
    p.push(tube([[-0.36, 0.31, -0.12], [-0.26, 0.43, -0.07], [-0.18, 0.45, 0], [-0.26, 0.43, 0.07], [-0.36, 0.31, 0.12]], 0.008));  // halo
    p.push(tube([[-0.18, 0.45, 0], [-0.08, 0.31, 0]], 0.008));
    p.push(box(0.1, 0.055, 0, 1.3, 0.015, 0.62));                       // floor
    p.push(box(-0.98, 0.07, 0, 0.2, 0.022, 0.96));                      // front wing
    p.push(box(-0.95, 0.12, 0, 0.12, 0.016, 0.9));
    p.push(box(-0.97, 0.1, 0.48, 0.22, 0.1, 0.012));
    p.push(box(-0.97, 0.1, -0.48, 0.22, 0.1, 0.012));
    p.push(box(0.92, 0.52, 0, 0.2, 0.025, 0.72));                       // rear wing
    p.push(box(0.94, 0.44, 0, 0.14, 0.018, 0.72));
    p.push(box(0.92, 0.4, 0.36, 0.3, 0.32, 0.012));
    p.push(box(0.92, 0.4, -0.36, 0.3, 0.32, 0.012));
    p.push(box(0.84, 0.32, 0, 0.04, 0.22, 0.04));                       // pylon
    [[-0.62, 0.47, 0.17, 0.16], [0.62, 0.46, 0.185, 0.21]].forEach(function (w) {   // wheels + arms
      [-1, 1].forEach(function (s) {
        p.push(cyl([w[0], w[2], s * w[1]], w[2], w[3], "z"));
        p.push(tube([[w[0] + 0.12, 0.27, s * 0.14], [w[0], w[2] + 0.04, s * (w[1] - w[3] / 2)]], 0.006));
        p.push(tube([[w[0] + 0.1, 0.13, s * 0.14], [w[0], w[2] - 0.04, s * (w[1] - w[3] / 2)]], 0.006));
      });
    });
    return { parts: p, shift: [0, -0.27, 0], scale: 1.0,
      name: "Formula 1 car", tag: "Motorsport", dims: "5630 × 2000 × 950 mm" };
  }
  function humanoid() {
    var p = [];
    p.push(ellip([0, 0.83, 0], 0.1, 0.125, 0.115));                     // head
    p.push(box(0, 0.83, 0.1, 0.15, 0.05, 0.03));                        // visor
    p.push(cyl([0, 0.67, 0], 0.04, 0.09, "y"));                         // neck
    p.push(box(0, 0.42, 0, 0.42, 0.4, 0.22));                           // chest
    p.push(box(0, 0.14, 0, 0.3, 0.16, 0.17));                           // abdomen
    p.push(box(0, -0.01, 0, 0.34, 0.12, 0.2));                          // pelvis
    [-1, 1].forEach(function (s) {
      p.push(ellip([s * 0.28, 0.56, 0], 0.075, 0.07, 0.075));            // shoulder
      p.push(cyl([s * 0.3, 0.37, 0], 0.05, 0.3, "y"));                   // upper arm
      p.push(ellip([s * 0.305, 0.21, 0], 0.05, 0.05, 0.05));             // elbow
      p.push(cyl([s * 0.31, 0.05, 0.02], 0.045, 0.28, "y"));             // forearm
      p.push(box(s * 0.31, -0.13, 0.02, 0.05, 0.11, 0.08));              // hand
      p.push(ellip([s * 0.1, -0.08, 0], 0.075, 0.06, 0.075));            // hip
      p.push(cyl([s * 0.1, -0.27, 0], 0.072, 0.36, "y"));                // thigh
      p.push(ellip([s * 0.1, -0.47, 0.01], 0.065, 0.06, 0.065));         // knee
      p.push(cyl([s * 0.1, -0.7, 0], 0.058, 0.4, "y"));                  // shin
      p.push(box(s * 0.1, -0.94, 0.045, 0.11, 0.06, 0.24));              // foot
    });
    return { parts: p, shift: [0, 0.04, 0], scale: 1.0,
      name: "Humanoid robot", tag: "Robotics", dims: "1750 mm · 28 DOF" };
  }
  function rocket() {
    var p = [], R = 0.12;
    p.push(cyl([0, -0.05, 0], R, 1.3, "y", false));                     // core stage
    p.push(cyl([0, 0.2, 0], R + 0.006, 0.025, "y", false));              // interstage ring
    p.push(cyl([0, -0.45, 0], R + 0.006, 0.02, "y", false));
    p.push(ellip([0, 0.6, 0], R, 0.36, R, 0));                          // fairing
    p.push(frustum([0, -0.78, 0], 0.06, 0.1, 0.16, "y"));                // engine bell
    [-1, 1].forEach(function (s) {                                      // boosters
      p.push(cyl([s * 0.2, -0.28, 0], 0.065, 0.84, "y", false));
      p.push(ellip([s * 0.2, 0.14, 0], 0.065, 0.16, 0.065, 0));
      p.push(frustum([s * 0.2, -0.76, 0], 0.04, 0.07, 0.12, "y"));
      p.push(tube([[s * 0.12, 0.05, 0], [s * 0.135, 0.05, 0]], 0.01));
    });
    for (var k = 0; k < 4; k++) {                                       // fins
      var a = (k / 4) * 2 * Math.PI + Math.PI / 4, cx = Math.cos(a), cz = Math.sin(a);
      p.push(tri([R * cx, -0.42, R * cz], [R * cx, -0.66, R * cz], [(R + 0.17) * cx, -0.72, (R + 0.17) * cz], 0.01));
    }
    return { parts: p, shift: [0, -0.02, 0], scale: 1.08,
      name: "Launch vehicle", tag: "Aerospace", dims: "70 m · Ø 3.7 m" };
  }
  function gearObj() {
    var p = [];
    p.push(gear([0, 0, 0], 24, 0.82, 0.71, 0.2, 0.16, 6, 0.1, 0.46));
    p.push(cyl([0, 0, 0], 0.3, 0.34, "y", false));                      // hub
    p.push(cyl([0, 0, 0], 0.2, 0.34, "y", false));                      // bore through hub
    p.push(cyl([0, 0.17, 0], 0.3, 0.001, "y"));
    p.push(cyl([0, -0.17, 0], 0.3, 0.001, "y"));
    return { parts: p, shift: [0, 0, 0], scale: 1.0, tilt: 0.55,
      name: "Spur gear", tag: "Industrial machinery", dims: "z 24 · m 3 · Ø 78 mm" };
  }

  function sample(def) {
    var A = 0, i, out = new Float32Array(N * 3);
    def.parts.forEach(function (q) { A += q.a; });
    var pts = [];
    def.parts.forEach(function (q) {
      var n = Math.max(6, Math.round((q.a / A) * N));
      for (i = 0; i < n; i++) pts.push(q.s());
    });
    while (pts.length > N) pts.splice(Math.floor(rnd() * pts.length), 1);
    while (pts.length < N) pts.push(def.parts[Math.floor(rnd() * def.parts.length)].s());
    // order by height so the cloud flows upward between shapes
    pts.sort(function (a, b) { return a[1] - b[1] || a[0] - b[0]; });
    var mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
    for (i = 0; i < N; i++) {
      for (var k = 0; k < 3; k++) {
        var v = (pts[i][k] + def.shift[k]) * def.scale;
        out[i * 3 + k] = v;
        if (v < mn[k]) mn[k] = v;
        if (v > mx[k]) mx[k] = v;
      }
    }
    def.pts = out; def.min = mn; def.max = mx;
    return def;
  }

  var shapes = [f1(), humanoid(), rocket(), gearObj()].map(sample);
  var jitter = new Float32Array(N * 3);
  for (var j = 0; j < N * 3; j++) jitter[j] = rr(-1, 1);
  var cur = new Float32Array(N * 3);

  // ---- HUD + tabs -----------------------------------------------------------
  var hudName = document.getElementById("hud-name"), hudDims = document.getElementById("hud-dims");
  var hudTag = document.getElementById("hud-tag"), hudPts = document.getElementById("hud-pts");
  var hudRot = document.getElementById("hud-rot");
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".stage__tabs button"));
  var tabWrap = document.querySelector(".stage__tabs");
  if (tabWrap) { tabWrap.style.setProperty("--hold", (HOLD + MORPH) / 1000 + "s"); if (reduce) tabWrap.classList.add("static"); }
  if (hudPts) hudPts.textContent = N.toLocaleString("en-US");

  var idx = 0, from = 0, phaseStart = 0, morphing = false;
  function label(i) {
    var s = shapes[i];
    if (hudName) hudName.textContent = s.name;
    if (hudDims) hudDims.textContent = s.dims;
    if (hudTag) hudTag.textContent = "FIG. 0" + (i + 1) + " — " + s.tag;
    tabs.forEach(function (t, k) {
      t.classList.remove("on");
      if (k === i) { void t.offsetWidth; t.classList.add("on"); t.setAttribute("aria-current", "true"); }
      else t.removeAttribute("aria-current");
    });
  }
  function go(i, now) {
    if (i === idx && !morphing) return;
    from = morphing ? -1 : idx;            // -1: morph from the in-between cloud
    if (from === -1) prevSnap.set(cur);
    idx = i; morphing = !reduce; phaseStart = now; label(i);
    if (reduce) cur.set(shapes[i].pts);
  }
  var prevSnap = new Float32Array(N * 3);
  tabs.forEach(function (t, k) { t.addEventListener("click", function () { go(k, performance.now()); draw(performance.now(), true); }); });

  // ---- camera + interaction -------------------------------------------------
  var W = 0, H = 0, dpr = 1, yaw = -0.6, pitch = -0.32, dragYaw = 0, drag = null, tiltNow = 0;
  function resize() {
    var r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  canvas.addEventListener("pointerdown", function (e) { drag = { x: e.clientX, y0: dragYaw }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", function (e) { if (drag) { dragYaw = drag.y0 + (e.clientX - drag.x) * 0.008; if (reduce) draw(performance.now(), true); } });
  ["pointerup", "pointercancel"].forEach(function (ev) { canvas.addEventListener(ev, function () { drag = null; }); });

  function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }

  var corners = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  var proj = new Float32Array(N * 3);

  function draw(now, force) {
    var t = now - phaseStart, k = 0, mix = 1;
    if (morphing) {
      mix = Math.min(1, t / MORPH);
      var e = ease(mix), A = from === -1 ? prevSnap : shapes[from].pts, B = shapes[idx].pts;
      var burst = Math.sin(Math.PI * mix) * 0.32;
      for (k = 0; k < N * 3; k++) cur[k] = A[k] + (B[k] - A[k]) * e + jitter[k] * burst;
      if (mix >= 1) { morphing = false; phaseStart = now; }
    } else if (!force && !reduce && t > HOLD) {
      go((idx + 1) % shapes.length, now);
    } else if (cur[0] === 0 && cur[1] === 0) {
      cur.set(shapes[idx].pts);
    }

    if (!reduce) yaw += 0.0026;
    var tiltTarget = shapes[idx].tilt || 0;
    tiltNow += (tiltTarget - tiltNow) * 0.04;
    var cy = Math.cos(yaw + dragYaw), sy = Math.sin(yaw + dragYaw);
    var pt = pitch - tiltNow, cp = Math.cos(pt), sp = Math.sin(pt);
    var S = Math.min(W * (small ? 0.42 : 0.37), H * 0.42), ox = W * (small ? 0.5 : 0.55), oy = H * 0.5, f = 3.4;

    function project(x, y, z, o, i) {
      var rx = x * cy - z * sy, rz = x * sy + z * cy;
      var ry = y * cp - rz * sp; rz = y * sp + rz * cp;
      var s = f / (f + rz);
      o[i] = ox + rx * S * s; o[i + 1] = oy - ry * S * s; o[i + 2] = rz;
    }

    ctx.clearRect(0, 0, W, H);

    // envelope brackets that morph with the object
    var s0 = shapes[idx], sa = morphing && from !== -1 ? shapes[from] : s0, em = morphing ? ease(mix) : 1;
    var mn = [0, 0, 0], mx = [0, 0, 0];
    for (k = 0; k < 3; k++) { mn[k] = sa.min[k] + (s0.min[k] - sa.min[k]) * em; mx[k] = sa.max[k] + (s0.max[k] - sa.max[k]) * em; }
    var c2 = new Float32Array(24);
    corners.forEach(function (c, i) { project(c[0] ? mx[0] : mn[0], c[1] ? mx[1] : mn[1], c[2] ? mx[2] : mn[2], c2, i * 3); });
    ctx.strokeStyle = "rgba(10,10,10,0.22)"; ctx.lineWidth = 1;
    var edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
    ctx.beginPath();
    edges.forEach(function (e) {                 // corner ticks only, 14% of each edge
      var ax = c2[e[0] * 3], ay = c2[e[0] * 3 + 1], bx = c2[e[1] * 3], by = c2[e[1] * 3 + 1];
      ctx.moveTo(ax, ay); ctx.lineTo(ax + (bx - ax) * 0.14, ay + (by - ay) * 0.14);
      ctx.moveTo(bx, by); ctx.lineTo(bx + (ax - bx) * 0.14, by + (ay - by) * 0.14);
    });
    ctx.stroke();

    // ground axes
    var ax3 = new Float32Array(12), gy = mn[1];
    project(0, gy, 0, ax3, 0); project(0.35, gy, 0, ax3, 3); project(0, gy, 0.35, ax3, 6); project(0, gy + 0.35, 0, ax3, 9);
    ctx.strokeStyle = "rgba(10,10,10,0.35)";
    ctx.beginPath();
    ctx.moveTo(ax3[0], ax3[1]); ctx.lineTo(ax3[3], ax3[4]);
    ctx.moveTo(ax3[0], ax3[1]); ctx.lineTo(ax3[6], ax3[7]);
    ctx.moveTo(ax3[0], ax3[1]); ctx.lineTo(ax3[9], ax3[10]);
    ctx.stroke();
    ctx.fillStyle = "rgba(10,10,10,0.45)"; ctx.font = "10px 'Geist Mono', monospace";
    ctx.fillText("X", ax3[3] + 4, ax3[4] + 3); ctx.fillText("Z", ax3[6] + 4, ax3[7] + 3); ctx.fillText("Y", ax3[9] - 3, ax3[10] - 6);

    // the cloud, depth-shaded in four alpha bands (batched for speed)
    for (k = 0; k < N; k++) project(cur[k * 3], cur[k * 3 + 1], cur[k * 3 + 2], proj, k * 3);
    var bands = [0.92, 0.62, 0.38, 0.2], sz = small ? 1.25 : 1.35;
    for (var b = 0; b < 4; b++) {
      ctx.fillStyle = "rgba(10,10,10," + bands[b] + ")";
      ctx.beginPath();
      for (k = 0; k < N; k++) {
        var z = proj[k * 3 + 2], band = z < -0.35 ? 0 : z < 0 ? 1 : z < 0.35 ? 2 : 3;
        if (band === b) ctx.rect(proj[k * 3] - sz / 2, proj[k * 3 + 1] - sz / 2, sz, sz);
      }
      ctx.fill();
    }

    if (hudRot) hudRot.textContent = (((((yaw + dragYaw) * 180) / Math.PI) % 360 + 360) % 360).toFixed(1).padStart(5, "0") + "°";
  }

  // ---- loop, paused when off-screen or hidden --------------------------------
  var visible = true, raf = 0;
  function loop(now) { draw(now); raf = visible && !reduce ? requestAnimationFrame(loop) : 0; }
  function kick() { if (!raf && visible && !reduce) raf = requestAnimationFrame(loop); }
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting && !document.hidden; kick(); }).observe(canvas);
  }
  document.addEventListener("visibilitychange", function () {
    visible = !document.hidden;
    if (visible) phaseStart = performance.now() - (morphing ? 0 : 0);
    kick();
  });
  var ro = window.ResizeObserver ? new ResizeObserver(function () { resize(); if (reduce) draw(performance.now(), true); }) : null;
  if (ro) ro.observe(canvas); else window.addEventListener("resize", resize);
  resize();
  label(0);
  cur.set(shapes[0].pts);
  phaseStart = performance.now();
  if (reduce) draw(performance.now(), true); else kick();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { if (reduce) draw(performance.now(), true); });
})();
