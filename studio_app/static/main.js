// Early stub — guarantees inline onclick handlers find SOMETHING callable
// even if a later import or runtime error aborts the module.
window.studio = window.studio || {
  toggleSource() { console.warn('studio: not ready'); },
  closeSource()  { console.warn('studio: not ready'); },
  openSource()   { console.warn('studio: not ready'); },
  loadExample()  { console.warn('studio: not ready'); },
  setMode()      { console.warn('studio: not ready'); },
};

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// =====================================================================
// Built-in examples
// =====================================================================
const EXAMPLES = {
  washer: `from build123d import *

# M4 Washer (DIN 125A)
outer_d = 9.0
inner_d = 4.3
thickness = 0.8

with BuildPart() as part:
    with BuildSketch():
        Circle(radius=outer_d / 2)
        Circle(radius=inner_d / 2, mode=Mode.SUBTRACT)
    extrude(amount=thickness)

result = part.part
`,
  bracket: `from build123d import *

base_l = 110
base_w = 80
base_t = 10
boss_d = 40
bore_d = 20
boss_w = 40
arm_t  = 12
height = 70
hole_d = 10
hx = 80
hy = 60

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        RectangleRounded(base_l, base_w, radius=6)
    extrude(amount=base_t)

    arm_h = height - base_t
    for sx in (-1, 1):
        with Locations((sx * (boss_w/2 - arm_t/2), 0, base_t)):
            Box(arm_t, boss_w, arm_h, align=(Align.CENTER, Align.CENTER, Align.MIN))

    with Locations((0, 0, height)):
        Cylinder(radius=boss_d/2, height=boss_w, rotation=(90, 0, 0))
    with Locations((0, 0, height)):
        Cylinder(radius=bore_d/2, height=boss_w + 2, rotation=(90, 0, 0), mode=Mode.SUBTRACT)

    for x in (-hx/2, hx/2):
        for y in (-hy/2, hy/2):
            with Locations((x, y, 0)):
                Cylinder(radius=hole_d/2, height=base_t + 2, mode=Mode.SUBTRACT)

result = part.part
`,
  flange: `from build123d import *

body_d   = 10.0
bore_d   = 5.0
body_h   = 32.0
flange_d = 18.0
flange_h = 4.0

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        Circle(flange_d / 2)
    extrude(amount=flange_h)

    with BuildSketch(Plane.XY.offset(flange_h)):
        Circle(body_d / 2)
    extrude(amount=body_h)

    with BuildSketch(Plane.XY):
        Circle(bore_d / 2)
    extrude(amount=flange_h + body_h, mode=Mode.SUBTRACT)

    chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=0.3)

result = part.part
`,
  gear: `from build123d import *
import math

n_teeth   = 18
module    = 2.0
thickness = 6.0
bore_d    = 8.0

pitch_r = module * n_teeth / 2
addendum = module
dedendum = 1.25 * module
outer_r = pitch_r + addendum
root_r = pitch_r - dedendum

pts = []
for i in range(n_teeth * 4):
    if i % 4 == 0:   r = root_r
    elif i % 4 == 1: r = pitch_r
    elif i % 4 == 2: r = outer_r
    else:            r = pitch_r
    a = 2 * math.pi * i / (n_teeth * 4)
    pts.append((r * math.cos(a), r * math.sin(a)))

with BuildPart() as part:
    with BuildSketch(Plane.XY):
        with BuildLine() as bl:
            Polyline(*pts, close=True)
        make_face()
        Circle(bore_d / 2, mode=Mode.SUBTRACT)
    extrude(amount=thickness)

result = part.part
`,
};

// =====================================================================
// DOM refs
// =====================================================================
const $ = (id) => document.getElementById(id);
const editor = $('editor');
const runBtn = $('run-btn');
const resetBtn = $('reset-btn');
const canvas = $('canvas');
const gizmoCanvas = $('gizmo');
const statusPill = $('status-pill');
const statusText = $('status-text');
const elapsedEl = $('elapsed');
const errDetail = $('err-detail');
const downloads = $('downloads');
const dlGlb = $('dl-glb');
const dlStep = $('dl-step');
const dlStl = $('dl-stl');
const emptyState = $('empty-state');
const loadingBar = $('loading-bar');
const statsCard = $('stats');
const consoleEl = $('console');
const consoleHead = $('console-head');
const consoleBody = $('console-body');

const chatScroll = $('chat-scroll');
const chatEmpty = $('chat-empty');
const chatForm = $('chat-form');
const chatInput = $('chat-input');
const sendBtn = $('send-btn');
const llmPill = $('llm-pill');
const llmPillText = $('llm-pill-text');
const historyStrip = $('history-strip');
const historyCount = $('history-count');
const paramsStrip = $('params-strip');
const selectionHint = $('selection-hint');

editor.value = EXAMPLES.bracket;

// =====================================================================
// Editor utility
// =====================================================================
editor.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = editor.selectionStart, t = editor.selectionEnd;
    editor.value = editor.value.slice(0, s) + '    ' + editor.value.slice(t);
    editor.selectionStart = editor.selectionEnd = s + 4;
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    runBtn.click();
  }
});
editor.addEventListener('input', () => rebuildParamSliders(editor.value));

// Example links are wired via inline onclick → window.studio.loadExample(name)
// (defined at the bottom of this file). Keeps the binding bullet-proof against
// browser-cache and module-load races.
resetBtn.addEventListener('click', () => {
  if (!confirm('Clear chat and code?')) return;
  editor.value = '';
  chatScroll.innerHTML = '';
  chatScroll.appendChild(chatEmpty);
  history.length = 0;
  rebuildHistoryStrip();
  rebuildParamSliders('');
});

$('console-close').addEventListener('click', () => consoleEl.classList.remove('visible'));

// =====================================================================
// Three.js scene (Z-up CAD convention)
// =====================================================================
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

function makePerspective() {
  const c = new THREE.PerspectiveCamera(40, 1, 0.1, 100000);
  c.position.set(140, -140, 110);
  c.up.set(0, 0, 1);
  return c;
}
let camera = makePerspective();
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.09;
controls.rotateSpeed = 0.75;
controls.zoomSpeed = 0.9;
controls.target.set(0, 0, 0);

const key  = new THREE.DirectionalLight(0xffffff, 0.6);  key.position.set(200, -250, 350);  scene.add(key);
const fill = new THREE.DirectionalLight(0xcfe0ff, 0.22); fill.position.set(-220, 100, 80);  scene.add(fill);
const rim  = new THREE.DirectionalLight(0xffe1bf, 0.18); rim.position.set(0, 250, -120);    scene.add(rim);

// Grid
let grid = null;
const gridParent = new THREE.Group();
scene.add(gridParent);
function rebuildGrid(maxDim) {
  if (grid) { gridParent.remove(grid); grid.geometry.dispose(); grid.material.dispose(); }
  const base = Math.max(50, Math.pow(10, Math.ceil(Math.log10(Math.max(maxDim, 10)))));
  const size = base * 4;
  grid = new THREE.GridHelper(size, 40, 0x6f7d92, 0xb3becf);
  grid.rotation.x = Math.PI / 2;
  grid.material.transparent = true;
  grid.material.opacity = 0.45;
  grid.material.depthWrite = false;
  gridParent.add(grid);
}
rebuildGrid(100);

// ===================================================================
// Origin frame
// ===================================================================
const originFrame = new THREE.Group();
scene.add(originFrame);

function textSprite(text, hex, fontPx = 56, bold = true) {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const ctx = c.getContext('2d');
  ctx.font = (bold ? 'bold ' : '') + fontPx + 'px -apple-system, "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 5;
  ctx.strokeText(text, 64, 70);
  ctx.fillStyle = hex;
  ctx.fillText(text, 64, 70);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  return new THREE.Sprite(m);
}

function makeOriginAxis(dir, color, hex, label, length) {
  const g = new THREE.Group();
  const shaftLen = length * 0.86;
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(length * 0.012, length * 0.012, shaftLen, 12),
    new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 })
  );
  shaft.position.copy(dir.clone().multiplyScalar(shaftLen / 2));
  shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  shaft.renderOrder = 999;
  g.add(shaft);
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(length * 0.04, length * 0.14, 16),
    new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 })
  );
  cone.position.copy(dir.clone().multiplyScalar(shaftLen + length * 0.07));
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  cone.renderOrder = 999;
  g.add(cone);
  const sp = textSprite(label, hex, 64, true);
  sp.position.copy(dir.clone().multiplyScalar(length * 1.08));
  sp.renderOrder = 1000;
  const ss = length * 0.12;
  sp.scale.set(ss, ss, ss);
  g.add(sp);
  return g;
}

function rebuildOriginFrame(maxDim) {
  while (originFrame.children.length) {
    const c = originFrame.children[0];
    originFrame.remove(c);
    c.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
  }
  const len = Math.max(maxDim * 0.45, 18);
  originFrame.add(makeOriginAxis(new THREE.Vector3(1, 0, 0), 0xe53935, '#c62828', 'X', len));
  originFrame.add(makeOriginAxis(new THREE.Vector3(0, 1, 0), 0x2e7d32, '#1b5e20', 'Y', len));
  originFrame.add(makeOriginAxis(new THREE.Vector3(0, 0, 1), 0x1565c0, '#0d47a1', 'Z', len));
  const sph = new THREE.Mesh(
    new THREE.SphereGeometry(len * 0.025, 16, 16),
    new THREE.MeshBasicMaterial({ color: 0x2a3340, depthTest: false })
  );
  sph.renderOrder = 999;
  originFrame.add(sph);
}
rebuildOriginFrame(60);

// ===================================================================
// Model + edges
// ===================================================================
const modelGroup = new THREE.Group();
scene.add(modelGroup);
const dimGroup = new THREE.Group();
scene.add(dimGroup);
const selectionGroup = new THREE.Group();
scene.add(selectionGroup);

let currentMesh = null;
let currentEdges = null;
let currentBBox = null;
let renderMode = 'shaded-edges';
let dimsVisible = true;
let currentMaxDim = 100;

// Sprites whose size should track screen-space (recomputed each frame).
const screenSpaceSprites = [];

function clearGroup(g) {
  while (g.children.length) {
    const c = g.children[0];
    g.remove(c);
    c.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        if (Array.isArray(o.material)) o.material.forEach(m => m.dispose());
        else o.material.dispose();
      }
    });
  }
}

function clearModel() {
  clearGroup(modelGroup);
  currentMesh = null; currentEdges = null; currentBBox = null;
}

function clearDims() {
  clearGroup(dimGroup);
  for (let i = screenSpaceSprites.length - 1; i >= 0; i--) {
    const s = screenSpaceSprites[i];
    if (!s.parent || s.parent === dimGroup || s.userData.__dimOwned) {
      screenSpaceSprites.splice(i, 1);
    }
  }
}

function loadSTL(url) {
  return new Promise((res, rej) => new STLLoader().load(url, res, undefined, rej));
}

// ===================================================================
// Dimension annotations  --  FIX: clamp sizes so labels never explode
// ===================================================================
const DIM_COLOR     = 0x14365e;
const DIM_LABEL_BG  = '#ffffff';
const DIM_LABEL_FG  = '#14365e';

// One-time texture-per-text-cache so we don't burn GPU memory.
const _dimTexCache = new Map();
function dimLabelTexture(text) {
  if (_dimTexCache.has(text)) return _dimTexCache.get(text);
  const c = document.createElement('canvas');
  c.width = 256; c.height = 80;
  const ctx = c.getContext('2d');
  ctx.fillStyle = DIM_LABEL_BG; ctx.strokeStyle = '#14365e'; ctx.lineWidth = 3;
  const r = 10;
  ctx.beginPath();
  ctx.moveTo(r, 2); ctx.lineTo(c.width - r, 2);
  ctx.quadraticCurveTo(c.width - 2, 2, c.width - 2, r);
  ctx.lineTo(c.width - 2, c.height - r);
  ctx.quadraticCurveTo(c.width - 2, c.height - 2, c.width - r, c.height - 2);
  ctx.lineTo(r, c.height - 2);
  ctx.quadraticCurveTo(2, c.height - 2, 2, c.height - r);
  ctx.lineTo(2, r);
  ctx.quadraticCurveTo(2, 2, r, 2);
  ctx.closePath();
  ctx.fill(); ctx.stroke();
  ctx.font = 'bold 38px "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = DIM_LABEL_FG;
  ctx.fillText(text, c.width / 2, c.height / 2 + 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  _dimTexCache.set(text, tex);
  return tex;
}

function dimLabelSprite(text) {
  const tex = dimLabelTexture(text);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sp = new THREE.Sprite(mat);
  // Aspect of the canvas (256:80 -> 3.2:1).
  sp.userData.__aspect = 3.2;
  sp.userData.__pxHeight = 24;       // desired on-screen height in pixels
  sp.userData.__dimOwned = true;
  sp.renderOrder = 1100;
  screenSpaceSprites.push(sp);
  return sp;
}

function lineSeg(pts, color = DIM_COLOR, opacity = 0.9) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false });
  const l = new THREE.LineSegments(g, m); l.renderOrder = 1050; return l;
}
function lineStrip(pts, color = DIM_COLOR, opacity = 0.9) {
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  const m = new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: false });
  const l = new THREE.Line(g, m); l.renderOrder = 1050; return l;
}
function arrowHead(at, dir, sz) {
  const cone = new THREE.Mesh(
    new THREE.ConeGeometry(sz * 0.35, sz, 12),
    new THREE.MeshBasicMaterial({ color: DIM_COLOR, depthTest: false })
  );
  cone.position.copy(at);
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  cone.renderOrder = 1060;
  return cone;
}

function makeDim(p1, p2, offDir, label, maxDim) {
  const out = new THREE.Group();

  // FIX: cap the offset between extension lines so dims don't drift miles away
  // from the part on small models, and don't disappear on huge ones.
  const off  = Math.min(Math.max(maxDim * 0.14, 6), maxDim * 0.45);
  const ext  = offDir.clone().normalize().multiplyScalar(off);
  const dp1  = p1.clone().add(ext);
  const dp2  = p2.clone().add(ext);

  const gap     = Math.min(maxDim * 0.012, 3);
  const gapDir  = offDir.clone().normalize().multiplyScalar(gap);
  out.add(lineSeg([p1.clone().add(gapDir), dp1, p2.clone().add(gapDir), dp2]));
  out.add(lineStrip([dp1, dp2]));

  const along = new THREE.Vector3().subVectors(dp2, dp1).normalize();
  // FIX: arrow size capped — was unbounded `maxDim * 0.028 + 0.4`.
  const arrowSz = Math.min(Math.max(maxDim * 0.02, 0.6), 3.5);
  out.add(arrowHead(dp1, along, arrowSz));
  out.add(arrowHead(dp2, along.clone().negate(), arrowSz));

  const mid = new THREE.Vector3().addVectors(dp1, dp2).multiplyScalar(0.5);
  const sp  = dimLabelSprite(label);
  sp.position.copy(mid).add(offDir.clone().normalize().multiplyScalar(off * 0.18 + 1.5));
  out.add(sp);
  return out;
}

function buildDimensions(bbox) {
  clearDims();
  if (!dimsVisible || !bbox) return;
  const sz = new THREE.Vector3(); bbox.getSize(sz);
  const maxDim = Math.max(sz.x, sz.y, sz.z, 1);
  const x0 = bbox.min.x, y0 = bbox.min.y, z0 = bbox.min.z;
  const x1 = bbox.max.x, y1 = bbox.max.y, z1 = bbox.max.z;

  dimGroup.add(makeDim(
    new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x1, y0, z0),
    new THREE.Vector3(0, -1, 0), `${sz.x.toFixed(2)} mm`, maxDim,
  ));
  dimGroup.add(makeDim(
    new THREE.Vector3(x1, y0, z0), new THREE.Vector3(x1, y1, z0),
    new THREE.Vector3(1, 0, 0), `${sz.y.toFixed(2)} mm`, maxDim,
  ));
  dimGroup.add(makeDim(
    new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x0, y0, z1),
    new THREE.Vector3(-1, 0, 0), `${sz.z.toFixed(2)} mm`, maxDim,
  ));
}

// ===================================================================
// Screen-space sprite scaling — keeps dimension labels constant size.
// ===================================================================
function updateScreenSpaceSprites() {
  if (!screenSpaceSprites.length) return;
  const h = canvas.clientHeight || 1;
  for (const sp of screenSpaceSprites) {
    if (!sp.parent) continue;
    const aspect = sp.userData.__aspect || 3.0;
    const pxH    = sp.userData.__pxHeight || 20;
    let worldH;
    if (camera.isPerspectiveCamera) {
      const dist = camera.position.distanceTo(sp.getWorldPosition(new THREE.Vector3()));
      const vFov = camera.fov * Math.PI / 180;
      const viewHeightAtDist = 2 * Math.tan(vFov / 2) * dist;
      worldH = (pxH / h) * viewHeightAtDist;
    } else {
      const viewHeight = camera.top - camera.bottom;
      worldH = (pxH / h) * viewHeight;
    }
    sp.scale.set(worldH * aspect, worldH, 1);
  }
}

// ===================================================================
// Show / render mode
// ===================================================================
async function showModel(url) {
  clearModel();
  loadingBar.classList.add('visible');
  try {
    const geom = await loadSTL(url);
    geom.computeVertexNormals();
    geom.computeBoundingBox();

    const mat = new THREE.MeshStandardMaterial({
      color: 0xd9dee5, metalness: 0.18, roughness: 0.5,
      envMapIntensity: 0.95, flatShading: false,
    });
    currentMesh = new THREE.Mesh(geom, mat);
    modelGroup.add(currentMesh);

    const edgeGeom = new THREE.EdgesGeometry(geom, 28);
    const edgeMat  = new THREE.LineBasicMaterial({ color: 0x0e1d33, transparent: true, opacity: 0.9 });
    edgeMat.polygonOffset = true; edgeMat.polygonOffsetFactor = -1;
    currentEdges = new THREE.LineSegments(edgeGeom, edgeMat);
    currentMesh.add(currentEdges);

    applyRenderMode();

    const bb = geom.boundingBox.clone();
    currentBBox = bb;
    const sz = new THREE.Vector3(); bb.getSize(sz);
    const maxDim = Math.max(sz.x, sz.y, sz.z, 1);
    currentMaxDim = maxDim;
    rebuildGrid(maxDim);
    rebuildOriginFrame(maxDim);
    buildDimensions(bb);

    emptyState.style.display = 'none';
    fitView();
  } catch (e) {
    console.error('STL load failed', e);
  } finally {
    loadingBar.classList.remove('visible');
  }
}

function applyRenderMode() {
  if (!currentMesh) return;
  currentMesh.visible = true;
  currentMesh.material.wireframe = renderMode === 'wireframe';
  if (currentEdges) currentEdges.visible = renderMode === 'shaded-edges';
}

document.querySelectorAll('#render-modes button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#render-modes button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    renderMode = b.dataset.mode;
    applyRenderMode();
  });
});

// ===================================================================
// View presets
// ===================================================================
let currentViewName = 'iso';

function setView(name) {
  let center = new THREE.Vector3(), maxDim = 100;
  if (currentMesh) {
    const bb = new THREE.Box3().setFromObject(currentMesh);
    bb.getCenter(center);
    const sz = new THREE.Vector3(); bb.getSize(sz);
    maxDim = Math.max(sz.x, sz.y, sz.z, 1);
  }
  const dist = maxDim * 2.6 + 8;
  controls.target.copy(center);
  const eps = dist * 0.0008;
  if (name === 'top')   camera.position.set(center.x + eps, center.y - eps * 2, center.z + dist);
  if (name === 'front') camera.position.set(center.x, center.y - dist, center.z + eps);
  if (name === 'right') camera.position.set(center.x + dist, center.y + eps, center.z + eps);
  if (name === 'iso')   camera.position.set(center.x + dist * 0.72, center.y - dist * 0.72, center.z + dist * 0.55);
  camera.up.set(0, 0, 1);
  controls.update();
}
function fitView() { setView(currentViewName); }

document.querySelectorAll('#view-presets button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#view-presets button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    currentViewName = b.dataset.view;
    setView(currentViewName);
  });
});

$('fit-btn').addEventListener('click', fitView);
$('dim-btn').addEventListener('click', (e) => {
  dimsVisible = !dimsVisible;
  e.currentTarget.classList.toggle('active', dimsVisible);
  if (currentMesh && currentBBox) buildDimensions(currentBBox); else clearDims();
});
$('grid-btn').addEventListener('click', (e) => {
  gridParent.visible = !gridParent.visible;
  e.currentTarget.classList.toggle('active', gridParent.visible);
});
$('axes-btn').addEventListener('click', (e) => {
  originFrame.visible = !originFrame.visible;
  e.currentTarget.classList.toggle('active', originFrame.visible);
});

let ortho = false;
$('ortho-btn').addEventListener('click', (e) => {
  ortho = !ortho;
  e.currentTarget.classList.toggle('active', ortho);
  swapCamera();
});

function swapCamera() {
  const oldPos = camera.position.clone();
  const oldTarget = controls.target.clone();
  const d = oldPos.distanceTo(oldTarget);
  if (ortho) {
    const aspect = canvas.clientWidth / Math.max(canvas.clientHeight, 1);
    const half = d * 0.55;
    camera = new THREE.OrthographicCamera(-half * aspect, half * aspect, half, -half, 0.1, 100000);
  } else {
    camera = makePerspective();
  }
  camera.position.copy(oldPos);
  camera.up.set(0, 0, 1);
  controls.object = camera;
  controls.target.copy(oldTarget);
  controls.update();
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  if (camera.isPerspectiveCamera) {
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  } else {
    const half = (camera.top - camera.bottom) / 2;
    const aspect = w / h;
    camera.left = -half * aspect; camera.right = half * aspect;
    camera.updateProjectionMatrix();
  }
}
new ResizeObserver(resize).observe(canvas);

// ===================================================================
// Gizmo
// ===================================================================
const gScene = new THREE.Scene();
const gCam = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
gCam.up.set(0, 0, 1);
const gRend = new THREE.WebGLRenderer({ canvas: gizmoCanvas, antialias: true, alpha: true });
gRend.setSize(96, 96, false);
gRend.setPixelRatio(Math.min(window.devicePixelRatio, 2));

function gizmoAxisLabel(letter, hex) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const ctx = c.getContext('2d');
  ctx.font = 'bold 44px -apple-system, "Segoe UI", sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineWidth = 4;
  ctx.strokeText(letter, 32, 36);
  ctx.fillStyle = hex; ctx.fillText(letter, 32, 36);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthTest: false }));
  s.scale.set(0.42, 0.42, 0.42); s.renderOrder = 10;
  return s;
}
function makeGizmoAxis(dir, colHex, hex, label) {
  const g = new THREE.Group();
  g.add(new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), dir.clone().multiplyScalar(0.85)]),
    new THREE.LineBasicMaterial({ color: colHex })
  ));
  const tip = new THREE.Mesh(
    new THREE.ConeGeometry(0.09, 0.22, 16),
    new THREE.MeshBasicMaterial({ color: colHex })
  );
  tip.position.copy(dir.clone().multiplyScalar(0.96));
  tip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  g.add(tip);
  const lbl = gizmoAxisLabel(label, hex);
  lbl.position.copy(dir.clone().multiplyScalar(1.18));
  g.add(lbl);
  return g;
}
gScene.add(makeGizmoAxis(new THREE.Vector3(1, 0, 0), 0xe53935, '#c62828', 'X'));
gScene.add(makeGizmoAxis(new THREE.Vector3(0, 1, 0), 0x2e7d32, '#1b5e20', 'Y'));
gScene.add(makeGizmoAxis(new THREE.Vector3(0, 0, 1), 0x1565c0, '#0d47a1', 'Z'));

function renderGizmo() {
  const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
  gCam.position.copy(dir.multiplyScalar(3.4));
  gCam.up.copy(camera.up);
  gCam.lookAt(0, 0, 0);
  gRend.render(gScene, gCam);
}

// ===================================================================
// Animation loop
// ===================================================================
function animate() {
  controls.update();
  updateScreenSpaceSprites();
  renderer.render(scene, camera);
  renderGizmo();
  requestAnimationFrame(animate);
}
resize();
setView('iso');
animate();

// ===================================================================
// Face raycasting (inspector)
// ===================================================================
const raycaster = new THREE.Raycaster();
const mouseNDC  = new THREE.Vector2();
let lastFaces = [];
let pickedSelection = null;

canvas.addEventListener('click', (ev) => {
  if (!currentMesh) return;
  const rect = canvas.getBoundingClientRect();
  mouseNDC.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  mouseNDC.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouseNDC, camera);
  const hits = raycaster.intersectObject(currentMesh, false);
  if (!hits.length) { clearPicked(); return; }
  const hit = hits[0];
  const pickedFace = pickClosestBackendFace(hit.point);
  highlightPick(hit);
  showSelection(pickedFace, hit.point);
});

function pickClosestBackendFace(pointWorld) {
  if (!lastFaces.length) return null;
  let best = null, bestD2 = Infinity;
  for (const f of lastFaces) {
    const c = f.center || [0, 0, 0];
    const dx = c[0] - pointWorld.x, dy = c[1] - pointWorld.y, dz = c[2] - pointWorld.z;
    const d2 = dx*dx + dy*dy + dz*dz;
    if (d2 < bestD2) { bestD2 = d2; best = f; }
  }
  return best;
}

function highlightPick(hit) {
  clearGroup(selectionGroup);
  const sph = new THREE.Mesh(
    new THREE.SphereGeometry(Math.max(currentMaxDim * 0.012, 0.6), 16, 16),
    new THREE.MeshBasicMaterial({ color: 0x4d9eff, depthTest: false, transparent: true, opacity: 0.85 })
  );
  sph.position.copy(hit.point); sph.renderOrder = 1500;
  selectionGroup.add(sph);
}

function clearPicked() {
  clearGroup(selectionGroup);
  pickedSelection = null;
  selectionHint.classList.remove('visible');
  selectionHint.innerHTML = '';
}

function showSelection(face, point) {
  if (!face) {
    pickedSelection = { face_index: -1, click_point: [point.x, point.y, point.z] };
    selectionHint.innerHTML =
      `<b>Picked point</b> at (${point.x.toFixed(2)}, ${point.y.toFixed(2)}, ${point.z.toFixed(2)}) ` +
      `<span class="clear" id="clear-sel">clear &#x2715;</span>`;
    selectionHint.classList.add('visible');
  } else {
    pickedSelection = { face_index: face.index, face_info: face };
    fetch('/api/inspect', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ face_index: face.index, face_info: face }),
    }).then(r => r.json()).then(data => {
      selectionHint.innerHTML =
        `<b>Selected</b> ${data.label || 'face ' + face.index} ` +
        `<span class="clear" id="clear-sel">clear &#x2715;</span>`;
      selectionHint.classList.add('visible');
      if (data.prefill && !chatInput.value.trim()) {
        chatInput.value = data.prefill;
        autoSizeChat();
      }
    }).catch(() => {});
  }
  setTimeout(() => {
    const c = document.getElementById('clear-sel');
    if (c) c.addEventListener('click', clearPicked);
  }, 0);
}

// ===================================================================
// History / versions
// ===================================================================
const history = [];   // [{ts, prompt, code, glb, step, stl, validation}]
let activeVersion = -1;

function rebuildHistoryStrip() {
  historyStrip.innerHTML = '';
  history.forEach((h, i) => {
    const el = document.createElement('div');
    el.className = 'v' + (i === activeVersion ? ' active' : '');
    el.textContent = `v${i + 1}`;
    el.title = h.prompt || '(no prompt)';
    el.addEventListener('click', () => restoreVersion(i));
    historyStrip.appendChild(el);
  });
  historyCount.textContent = `${history.length} run${history.length === 1 ? '' : 's'}`;
}

function pushVersion(payload) {
  history.push(payload);
  activeVersion = history.length - 1;
  rebuildHistoryStrip();
}

function restoreVersion(i) {
  const v = history[i]; if (!v) return;
  editor.value = v.code;
  rebuildParamSliders(v.code);
  activeVersion = i;
  rebuildHistoryStrip();
  if (v.stl_url) showModel(v.stl_url);
  if (v.glb_url) dlGlb.href = v.glb_url;
  if (v.step_url) dlStep.href = v.step_url;
  if (v.stl_url) dlStl.href = v.stl_url;
  downloads.classList.add('visible');
}

// ===================================================================
// Parameter sliders
// ===================================================================
const PARAM_RE = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?\d+(?:\.\d+)?)\s*$/;

function listParameters(code) {
  const out = [];
  code.split('\n').forEach(line => {
    const m = line.trim().match(PARAM_RE);
    if (m && !m[1].startsWith('_') && m[1] !== m[1].toUpperCase()) {
      out.push({ name: m[1], value: parseFloat(m[2]), raw: m[2] });
    }
  });
  return out;
}

function rebuildParamSliders(code) {
  paramsStrip.innerHTML = '';
  const params = listParameters(code);
  if (!params.length) return;
  for (const p of params) {
    const box = document.createElement('div'); box.className = 'param';
    const name = document.createElement('div'); name.className = 'pname'; name.textContent = p.name;
    const row  = document.createElement('div'); row.className = 'prow';
    const range = document.createElement('input'); range.type = 'range';
    const value = Math.max(0.01, p.value);
    range.min = (value * 0.1).toFixed(3);
    range.max = (value * 3).toFixed(3);
    range.step = (value * 0.01).toFixed(4);
    range.value = p.value;
    const num = document.createElement('input'); num.type = 'number';
    num.value = p.value; num.step = (Math.max(0.01, value * 0.05)).toFixed(2);
    function apply(v) {
      const code = editor.value;
      const re = new RegExp(`^(\\s*${p.name}\\s*=\\s*)[-+]?\\d+(?:\\.\\d+)?`, 'm');
      editor.value = code.replace(re, (_, prefix) => prefix + v);
    }
    range.addEventListener('input', () => { num.value = range.value; apply(range.value); });
    num.addEventListener('input', () => { range.value = num.value; apply(num.value); });
    row.appendChild(range); row.appendChild(num);
    box.appendChild(name); box.appendChild(row);
    paramsStrip.appendChild(box);
  }
}
rebuildParamSliders(editor.value);

// ===================================================================
// Chat
// ===================================================================
const chatHistory = [];   // [{role, content}]

function addMessage(role, content, opts = {}) {
  if (chatEmpty.parentNode === chatScroll) chatScroll.removeChild(chatEmpty);
  const m = document.createElement('div');
  m.className = 'msg ' + (role === 'user' ? 'user' : 'asst') + (opts.typing ? ' typing' : '');
  const av = document.createElement('div'); av.className = 'avatar';
  av.textContent = role === 'user' ? 'You' : 'OF';
  const b  = document.createElement('div'); b.className = 'bubble' + (opts.error ? ' error' : '');
  if (opts.typing) {
    b.innerHTML = '<span class="dots"><span></span><span></span><span></span></span> thinking&hellip;';
  } else {
    b.innerHTML = escapeHTML(content);
    if (opts.badge) {
      const sp = document.createElement('span');
      sp.className = 'badge'; sp.textContent = opts.badge;
      b.appendChild(sp);
    }
  }
  m.appendChild(av); m.appendChild(b);
  chatScroll.appendChild(m);
  chatScroll.scrollTop = chatScroll.scrollHeight;
  return m;
}

function escapeHTML(s) {
  return String(s).replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}

function autoSizeChat() {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
  const composer = chatInput.closest('.composer');
  if (composer) composer.classList.toggle('empty', !chatInput.value.trim());
}
chatInput.addEventListener('input', autoSizeChat);
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelectorAll('.chip').forEach(c => {
  c.addEventListener('click', () => {
    chatInput.value = c.dataset.suggest;
    autoSizeChat();
    chatInput.focus();
  });
});

// Initial empty-state class so the send button starts dimmed.
autoSizeChat();

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const prompt = chatInput.value.trim();
  if (!prompt) return;
  const mode = currentMode;

  addMessage('user', prompt);
  chatHistory.push({ role: 'user', content: prompt });
  chatInput.value = ''; autoSizeChat();
  sendBtn.disabled = true;
  const typing = addMessage('assistant', '', { typing: true });

  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt, history: chatHistory.slice(0, -1),
        current_code: editor.value, mode,
      }),
    });
    const data = await res.json();
    typing.remove();
    if (!data.ok) {
      addMessage('assistant', data.reply || data.error || 'Something went wrong.', { error: true });
      chatHistory.push({ role: 'assistant', content: data.reply || data.error || '' });
      return;
    }
    editor.value = data.code;
    rebuildParamSliders(data.code);
    if (typeof setCodeOpen === 'function') setCodeOpen(true);
    addMessage('assistant', data.reply || 'Done.', {
      badge: `${data.route}${data.source ? ' · ' + data.source : ''}`,
    });
    chatHistory.push({ role: 'assistant', content: data.reply || '' });
    if (data.route === 'generate' || data.source === 'llm' || data.source === 'heuristic') {
      runBtn.click();
    }
  } catch (err) {
    typing.remove();
    addMessage('assistant', 'Chat request failed: ' + err.message, { error: true });
  } finally {
    sendBtn.disabled = false;
  }
});

// ===================================================================
// LLM status pill
// ===================================================================
async function refreshLLMStatus() {
  try {
    const r = await fetch('/api/status'); const d = await r.json();
    if (d.llm_ready) {
      llmPill.className = 'header-pill ok';
      llmPillText.textContent = 'Copilot ready';
    } else {
      llmPill.className = 'header-pill warn';
      llmPillText.textContent = 'Copilot offline';
      llmPill.title = d.detail || 'Set GROQ_API_KEY to enable the copilot';
    }
  } catch (err) {
    llmPill.className = 'header-pill err';
    llmPillText.textContent = 'Copilot unreachable';
  }
}
refreshLLMStatus();

// ===================================================================
// Source drawer + mode pills + example loader
// (All exposed via window.studio so inline onclick handlers work even if
//  the module fails to bind delegated listeners on some browsers.)
// ===================================================================
const gridEl = document.getElementById('grid');
const codeToggle = document.getElementById('code-toggle');
let currentMode = 'generate';

function setCodeOpen(open) {
  if (!gridEl) return;
  gridEl.classList.toggle('code-closed', !open);
  if (codeToggle) codeToggle.classList.toggle('active', open);
  setTimeout(resize, 300);
}
setCodeOpen(false);

function toggleSource() {
  setCodeOpen(gridEl.classList.contains('code-closed'));
}

function closeSource() { setCodeOpen(false); }
function openSource()  { setCodeOpen(true); }

function loadExample(name) {
  const code = EXAMPLES[name];
  if (!code) return;
  editor.value = code;
  rebuildParamSliders(code);
  openSource();
  editor.focus();
}

function setMode(mode) {
  if (mode !== 'generate' && mode !== 'edit') return;
  currentMode = mode;
  document.querySelectorAll('.mode-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.mode === mode);
  });
}

window.studio = { toggleSource, closeSource, openSource, loadExample, setMode };

// ESC also closes the drawer.
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && gridEl && !gridEl.classList.contains('code-closed')) {
    setCodeOpen(false);
  }
});

// ===================================================================
// Run pipeline
// ===================================================================
function setStatus(state, text, errText) {
  statusPill.className = 'pill ' + state;
  statusPill.textContent = state;
  statusText.textContent = text || '';
  errDetail.textContent = errText || '';
}

async function runCode() {
  setStatus('running', 'Compiling build123d code', '');
  elapsedEl.textContent = '';
  downloads.classList.remove('visible');
  statsCard.classList.remove('visible');
  consoleEl.classList.remove('visible');
  runBtn.disabled = true;
  loadingBar.classList.add('visible');
  try {
    const res = await fetch('/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: '', code: editor.value }),
    });
    const data = await res.json();
    elapsedEl.textContent = data.elapsed_ms ? `${data.elapsed_ms} ms` : '';
    if (!data.ok) {
      setStatus('err', data.error_type || 'Error', data.error || '');
      consoleHead.textContent = `${data.error_type}: ${data.error}`;
      const parts = [];
      if (data.stdout)    parts.push('— stdout —\n' + data.stdout);
      if (data.traceback) parts.push('— traceback —\n' + data.traceback);
      if (data.available_vars) parts.push('available vars: ' + data.available_vars.join(', '));
      consoleBody.textContent = parts.join('\n\n');
      consoleEl.classList.add('visible');
      return;
    }
    dlGlb.href = data.glb_url; dlStep.href = data.step_url; dlStl.href = data.stl_url;
    downloads.classList.add('visible');

    const v = data.validation || {};
    $('s-vol').textContent = (v.volume_mm3 ?? 0).toLocaleString() + ' mm³';
    if (v.bbox) {
      const s = v.bbox.size, c = v.bbox.center;
      $('s-bbox').textContent  = `${s[0]} × ${s[1]} × ${s[2]} mm`;
      $('s-center').textContent = `${c[0]}, ${c[1]}, ${c[2]}`;
    }
    if (v.topology) {
      const t = v.topology;
      $('s-topo').textContent = `${t.faces}F / ${t.edges}E / ${t.vertices}V`;
    }
    const wt = $('s-wt');
    if (v.watertight === true)       { wt.textContent = 'yes'; wt.className = 'val ok'; }
    else if (v.watertight === false) { wt.textContent = 'no';  wt.className = 'val err'; }
    else                              { wt.textContent = '?';   wt.className = 'val'; }
    statsCard.classList.add('visible');

    lastFaces = data.faces || [];
    setStatus('ok', 'Compiled successfully', '');
    await showModel(data.stl_url + '?t=' + Date.now());

    pushVersion({
      ts: Date.now(), prompt: '', code: editor.value,
      glb_url: data.glb_url, step_url: data.step_url, stl_url: data.stl_url,
      validation: v,
    });
  } catch (err) {
    setStatus('err', 'Request failed', err.message);
  } finally {
    runBtn.disabled = false;
    loadingBar.classList.remove('visible');
  }
}
runBtn.addEventListener('click', runCode);
