// The Last Wheel — la ville en 3D, pilotée par l'état servi par la simulation (/api/state).
// Chargé par main.js seulement si le navigateur sait faire de la 3D (WebGL).
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { cap, fallback, startHud } from "./hud.js";

const $ = (id) => document.getElementById(id);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = matchMedia("(pointer: coarse)").matches || innerWidth < 900;

// ------------------------------------------------------------- ambiances ---
// Couleurs de ciel/brouillard et intensités, selon jour/nuit/hibernation et météo.
const LOOK = {
  day:    { sky: "#5f7698", sun: 2.3, sunColor: "#cddcff", hemi: 1.15, fog: 0.009 },
  night:  { sky: "#0d1830", sun: 0.35, sunColor: "#7a90d0", hemi: 0.28, fog: 0.010 },
  frozen: { sky: "#222d44", sun: 0.45, sunColor: "#8fa2c8", hemi: 0.42, fog: 0.014 },
};
const WEATHER = {
  clear:    { snow: 0.12, wind: 0.6, fog: 0.75, white: 0.0,  outside: 1.0 },
  wind:     { snow: 0.45, wind: 6.0, fog: 1.15, white: 0.08, outside: 0.6 },
  snow:     { snow: 0.7,  wind: 1.4, fog: 1.3,  white: 0.1,  outside: 0.8 },
  blizzard: { snow: 1.0,  wind: 13,  fog: 2.0,  white: 0.45, outside: 0.25 },
};
const WHITEOUT = new THREE.Color("#a9b6c8");

// --------------------------------------------------------------- moteur ---
const renderer = new THREE.WebGLRenderer({ antialias: !mobile, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, mobile ? 1.5 : 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.localClippingEnabled = true;
$("view").appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(LOOK.night.sky);
scene.fog = new THREE.FogExp2(LOOK.night.sky, LOOK.night.fog);
// Sur écran étroit la caméra recule (voir resize): on réduit le brouillard en proportion
// pour que la ville garde la même netteté que sur PC et ne soit pas voilée.
let fogScale = 1, fogFit = 46;

const camera = new THREE.PerspectiveCamera(40, 1, 0.5, 400);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.8, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enablePan = false;
controls.minDistance = 12;
controls.maxPolarAngle = 1.18; // jamais sous le bord du cratère
controls.minPolarAngle = 0.25;
controls.rotateSpeed = 0.6;
controls.zoomSpeed = 0.8;
controls.autoRotateSpeed = 0.25;
let lastInteraction = performance.now();
controls.addEventListener("start", () => { controls.autoRotate = false; lastInteraction = performance.now(); });
controls.addEventListener("end", () => { lastInteraction = performance.now(); });

const hemi = new THREE.HemisphereLight("#b8c8e8", "#3c4458", LOOK.night.hemi);
scene.add(hemi);
const sun = new THREE.DirectionalLight(LOOK.night.sunColor, LOOK.night.sun);
sun.position.set(-28, 22, -18); // soleil rasant: longues ombres
sun.castShadow = true;
sun.shadow.mapSize.set(mobile ? 1024 : 2048, mobile ? 1024 : 2048);
Object.assign(sun.shadow.camera, { left: -32, right: 32, top: 32, bottom: -32, near: 1, far: 120 });
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.04;
scene.add(sun);
const heat = new THREE.PointLight("#ff9440", 0, 26, 1.2); // la flaque de chaleur de la centrale
heat.position.set(0, 4.2, 0);
scene.add(heat);

// post-traitement: halo des lumières (bloom), désactivé sur mobile ou si la machine rame
let composer = null, bloom = null;
function setupBloom() {
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.55, 0.82);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());
}
if (!mobile) setupBloom();

// ----------------------------------------------------------- la ville 3D ---
const buildings = {};     // id -> [exemplaire, ...] ; exemplaire = { group, meshes, ghost, plane, mode... }
const instances = [];     // tous les exemplaires, à plat
const emissive = {};      // nom du matériau -> { mat, base }
const tinted = [];        // matériaux qui se couvrent de givre: { mat, base: Color }
const baseColor = new Map(); // matériau d'origine -> couleur sans givre
const emitters = [];      // points de fumée: { pos, kind, building }
let wheel = null, layout = null, cityReady = false;
const ghostFace = new THREE.MeshBasicMaterial({ color: "#9fd0ff", transparent: true, opacity: 0.07, depthWrite: false });
const ghostEdge = new THREE.LineBasicMaterial({ color: "#a8d6ff", transparent: true, opacity: 0.55 });

function stripGeometry(g) {
  for (const name of Object.keys(g.attributes)) if (name !== "position" && name !== "normal") g.deleteAttribute(name);
  return g.index ? g : g.setIndex([...Array(g.attributes.position.count).keys()]);
}

// Fusionne les maillages d'un sous-arbre par matériau (beaucoup moins d'appels de dessin).
function mergeSubtree(root, parent, skip = new Set()) {
  root.updateWorldMatrix(true, true);
  const inv = new THREE.Matrix4().copy(parent.matrixWorld).invert();
  const byMat = new Map(), dead = [];
  root.traverse((o) => {
    if (!o.isMesh || [...skip].some((s) => isInside(o, s))) return;
    const g = stripGeometry(o.geometry.clone());
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
    if (!byMat.has(o.material)) byMat.set(o.material, []);
    byMat.get(o.material).push(g);
    dead.push(o);
  });
  for (const o of dead) o.removeFromParent();
  const out = [];
  for (const [mat, geos] of byMat) {
    const mesh = new THREE.Mesh(mergeGeometries(geos, false), mat);
    mesh.castShadow = mesh.receiveShadow = true;
    parent.add(mesh);
    out.push(mesh);
  }
  return out;
}
function isInside(o, root) { for (let p = o; p; p = p.parent) if (p === root) return true; return false; }

function prepareMaterials(root) {
  const seen = new Set();
  root.traverse((o) => {
    if (!o.isMesh || seen.has(o.material)) return;
    const m = o.material;
    seen.add(m);
    m.side = THREE.FrontSide;
    m.flatShading = true;
    m.roughness = 1;
    m.metalness = 0;
    const key = m.name.replace(/^TLW_/, "");
    if (["fire", "window", "greenhouse"].includes(key)) {
      emissive[key] = { mat: m, base: { fire: 3.2, window: 2.4, greenhouse: 0.9 }[key] };
      m.toneMapped = true;
    } else {
      baseColor.set(m, m.color.clone());
      tinted.push({ mat: m, base: baseColor.get(m) });
    }
  });
}

function loadCity() {
  return new Promise((resolve, reject) => {
    new GLTFLoader().load("assets/city.glb", resolve, (e) => {
      if (e.total) $("loading-text").textContent = `Lighting the furnace… ${Math.round(100 * e.loaded / e.total)}%`;
    }, reject);
  });
}

async function buildCity(catalog) {
  const gltf = await loadCity();
  const root = gltf.scene;
  scene.add(root);
  prepareMaterials(root);
  root.updateWorldMatrix(true, true);

  const fx = root.getObjectByName("TLW_fx");
  try { layout = JSON.parse(fx?.userData?.tlw || "null"); } catch { layout = null; }
  // Fallback si le GLB a été exporté avant que TLW_fx.tlw soit ajouté (Blender frost style)
  if (!layout) {
    const STEP = 2 * Math.PI / 7, ST = -Math.PI / 2 - STEP / 2;
    const angs = Array.from({length: 7}, (_, i) => parseFloat((ST + STEP * (i + 0.5)).toFixed(5)));
    const ends = [17.7, 10.85, 17.7, 10.85, 17.7, 10.85, 10.85];
    layout = { paths: angs, path_ends: ends, path_start: 4.2, path_end: 17.7, ring: 9.85, plaza: 4.6 };
  }
  for (const name of ["TLW_land", "TLW_fx"]) {
    const node = root.getObjectByName(name);
    if (node) mergeSubtree(node, node);
  }
  // caisses de ravitaillement : scale 1→0 sur leur plage WU, pilotées par infraState
  for (let k = 1; k <= 5; k++) {
    const name = `TLW_supply_${k}`;
    const node = root.getObjectByName(name);
    if (node) { mergeSubtree(node, node); infraState.set(name, { obj: node, current: 1, target: 1 }); }
  }
  // infrastructure progressive : scale 0→1 sur leur plage WU, cachées jusqu'à leur seuil
  const INFRA_KEYS = [
    "TLW_infra_tracks_s1", "TLW_infra_tracks_s2", "TLW_infra_tracks_s3",
    ...Array.from({ length: 7 }, (_, i) => `TLW_infra_path_${i}`),
    "TLW_infra_village",
    "TLW_infra_ring_n1",   "TLW_infra_ring_n2",   "TLW_infra_ring_n3",   "TLW_infra_ring_n4",
    ...Array.from({ length: 8 }, (_, i) => `TLW_infra_lamp_${i + 1}`),
    "TLW_infra_ring_n5",   "TLW_infra_ring_n6",
    "TLW_infra_paths_s4",  "TLW_infra_paths_s5",
    ...Array.from({ length: 4 }, (_, i) => `TLW_infra_lamp_${i + 9}`),
  ];
  for (const name of INFRA_KEYS) {
    const node = root.getObjectByName(name);
    if (node) { mergeSubtree(node, node); node.visible = false; infraState.set(name, { obj: node, current: 0, target: 0 }); }
  }
  // Avertissement visible si des objets 3D sont absents du GLB
  const missing3d = INFRA_KEYS.filter(n => !infraState.has(n));
  if (missing3d.length > 0) {
    console.warn("[TLW] objets infra absents du GLB:", missing3d);
    const el = document.createElement("div");
    el.id = "tlw-missing-warn";
    el.style.cssText = "position:fixed;top:0;left:0;right:0;background:#b00;color:#fff;padding:3px 8px;font:11px monospace;z-index:9999;pointer-events:none;";
    el.textContent = `[DEV] ${missing3d.length} objet(s) 3D manquants: ${missing3d.join(", ")}`;
    document.body.appendChild(el);
  }

  // la centrale (la Roue reste à part pour pouvoir tourner)
  const gen = root.getObjectByName("TLW_generator");
  wheel = root.getObjectByName("TLW_wheel");
  if (gen) {
    heat.position.setFromMatrixPosition(gen.matrixWorld).setY(4.2);
    mergeSubtree(gen, gen, new Set(wheel ? [wheel] : []));
    if (wheel) mergeSubtree(wheel, wheel);
  }

  // points de fumée
  root.traverse((o) => {
    if (!o.name.startsWith("TLW_smoke_")) return;
    let owner = null;
    for (let p = o.parent; p; p = p.parent) if (p.name.startsWith("TLW_") && p !== root) { owner = p.name.slice(4); break; }
    emitters.push({ pos: new THREE.Vector3().setFromMatrixPosition(o.matrixWorld),
      kind: o.name.startsWith("TLW_smoke_gen") ? "gen" : "building", building: owner, acc: 0 });
  });

  // bâtiments constructibles: TLW_<id>, puis TLW_<id>_2, TLW_<id>_3... pour les bâtiments multiples
  for (const b of catalog) {
    if (b.id === "generator") continue;
    buildings[b.id] = [];
    for (let k = 1; ; k++) {
      const group = root.getObjectByName(k === 1 ? `TLW_${b.id}` : `TLW_${b.id}_${k}`);
      if (!group) break;
      const inst = makeInstance(group, b);
      buildings[b.id].push(inst);
      instances.push(inst);
    }
  }
  cityReady = true;
  if (lastState) applyState(lastState);
  $("loading").hidden = true;
  requestAnimationFrame(frame);
}

function makeInstance(group, def) {
  const meshes = mergeSubtree(group, group);
  const box = new THREE.Box3();
  for (const m of meshes) { m.geometry.computeBoundingBox(); box.union(m.geometry.boundingBox); }
  const ghost = new THREE.Group(); // le "plan" du bâtiment pendant le chantier
  for (const m of meshes) {
    ghost.add(new THREE.Mesh(m.geometry, ghostFace));
    ghost.add(new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 25), ghostEdge));
  }
  group.add(ghost);
  const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
  const clipped = meshes.map((m) => {
    const mat = m.material.clone();
    mat.clippingPlanes = [plane];
    mat.clipShadows = true;
    if (baseColor.has(m.material)) tinted.push({ mat, base: baseColor.get(m.material) });
    return mat;
  });
  group.visible = false;
  const inst = { id: def.id, name: def.name, group, meshes, ghost, plane, clipped, solid: meshes.map((m) => m.material),
    y0: box.min.y, height: Math.max(box.max.y - box.min.y, 0.1), mode: "hidden", pop: 1, seen: false };
  for (const m of meshes) m.userData.instance = inst;
  return inst;
}

function setBuildingMode(b, mode, pct) {
  if (mode === "construction") {
    const cut = b.y0 + b.height * Math.min(Math.max(pct / 100, 0.02), 1);
    b.plane.constant = cut; // garde tout ce qui est sous la ligne de chantier
  }
  const firstLook = !b.seen;
  b.seen = true;
  if (mode === b.mode) return;
  const wasBuilt = b.mode === "built";
  b.mode = mode;
  b.group.visible = mode !== "hidden";
  b.ghost.visible = mode === "construction";
  b.meshes.forEach((m, i) => { m.material = mode === "construction" ? b.clipped[i] : b.solid[i]; });
  if (mode === "built" && !wasBuilt && !firstLook) b.pop = 0; // petit "pop" quand il vient d'être fini
}

// ----------------------------------------------------------------- fumée ---
const SMOKE_MAX = mobile ? 80 : 260;
const smokeGeo = new THREE.IcosahedronGeometry(1, 0);
const smokeMat = new THREE.MeshLambertMaterial({ color: "#e4e8f0", emissive: "#3b4458", flatShading: true });
const smoke = new THREE.InstancedMesh(smokeGeo, smokeMat, SMOKE_MAX);
smoke.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
smoke.frustumCulled = false;
scene.add(smoke);
const puffs = Array.from({ length: SMOKE_MAX }, () => ({ alive: false, p: new THREE.Vector3(), v: new THREE.Vector3(), age: 0, life: 1, size: 1, spin: 0 }));
const tmpM = new THREE.Matrix4(), tmpQ = new THREE.Quaternion(), tmpS = new THREE.Vector3(), tmpE = new THREE.Euler();

function emitPuff(e, big) {
  const p = puffs.find((x) => !x.alive);
  if (!p) return;
  p.alive = true;
  p.p.copy(e.pos);
  p.p.x += (Math.random() - 0.5) * 0.3;
  p.p.z += (Math.random() - 0.5) * 0.3;
  p.v.set((Math.random() - 0.5) * 0.25, (big ? 1.5 : 0.9) + Math.random() * 0.4, (Math.random() - 0.5) * 0.25);
  p.age = 0;
  p.life = (big ? 7 : 4.5) + Math.random() * 2;
  p.size = big ? 0.42 : 0.22;
  p.spin = Math.random() * 6;
}

function updateSmoke(dt, wind) {
  for (const e of emitters) {
    let rate = 0;
    if (e.kind === "gen") rate = (sim.frozen && !sim.active) ? 0 : 1.4 + 3.2 * sim.heatK;
    else if (buildings[e.building]?.[0]?.mode === "built" && !sim.frozen) rate = 0.9;
    e.acc += rate * dt;
    while (e.acc >= 1) { e.acc -= 1; emitPuff(e, e.kind === "gen"); }
  }
  let n = 0;
  for (const p of puffs) {
    if (!p.alive) continue;
    p.age += dt;
    if (p.age >= p.life) { p.alive = false; continue; }
    const k = p.age / p.life;
    p.v.y *= 1 - 0.18 * dt;
    p.p.addScaledVector(p.v, dt);
    p.p.x += wind * 0.35 * dt;          // le vent couche la fumée
    p.p.z += wind * 0.12 * dt;
    const s = p.size * (1 + 2.6 * k) * (k > 0.8 ? (1 - k) / 0.2 : 1);
    tmpS.setScalar(Math.max(s, 0.001));
    tmpQ.setFromEuler(tmpE.set(p.spin + k, p.spin * 0.7, 0));
    smoke.setMatrixAt(n++, tmpM.compose(p.p, tmpQ, tmpS));
  }
  smoke.count = n;
  smoke.instanceMatrix.needsUpdate = true;
}

// ----------------------------------------------------------------- neige ---
const SNOW_MAX = mobile ? 1500 : 7000;
const SNOW_BOX = { x: 70, y: 36, z: 70 };
const snowPos = new Float32Array(SNOW_MAX * 3), snowSpeed = new Float32Array(SNOW_MAX);
for (let i = 0; i < SNOW_MAX; i++) {
  snowPos[i * 3] = (Math.random() - 0.5) * SNOW_BOX.x;
  snowPos[i * 3 + 1] = Math.random() * SNOW_BOX.y;
  snowPos[i * 3 + 2] = (Math.random() - 0.5) * SNOW_BOX.z;
  snowSpeed[i] = 1.2 + Math.random() * 1.4;
}
const snowGeo = new THREE.BufferGeometry();
snowGeo.setAttribute("position", new THREE.BufferAttribute(snowPos, 3).setUsage(THREE.DynamicDrawUsage));
const snow = new THREE.Points(snowGeo, new THREE.PointsMaterial({ color: "#eef3fb", size: 0.16, transparent: true, opacity: 0.9, depthWrite: false }));
snow.frustumCulled = false;
scene.add(snow);

function updateSnow(dt, amount, wind) {
  const n = Math.floor(SNOW_MAX * amount);
  snowGeo.setDrawRange(0, n);
  const slow = reduced ? 0.4 : 1;
  for (let i = 0; i < n; i++) {
    const j = i * 3;
    snowPos[j + 1] -= snowSpeed[i] * dt * slow * (1 + wind * 0.05);
    snowPos[j] += (wind + Math.sin(snowPos[j + 1] * 0.4 + i) * 0.5) * dt * slow;
    if (snowPos[j + 1] < 0) { snowPos[j + 1] = SNOW_BOX.y; snowPos[j] = (Math.random() - 0.5) * SNOW_BOX.x; }
    if (snowPos[j] > SNOW_BOX.x / 2) snowPos[j] -= SNOW_BOX.x;
  }
  snowGeo.attributes.position.needsUpdate = true;
}

// ------------------------------------------------------------- habitants ---
const PEOPLE_MAX = 100;
let habCfg = {}, habCarrierCount = 0;

function habFillColors(geo, col) {
  const c = new THREE.Color(col), n = geo.attributes.position.count;
  const buf = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { buf[i*3]=c.r; buf[i*3+1]=c.g; buf[i*3+2]=c.b; }
  geo.setAttribute("color", new THREE.BufferAttribute(buf, 3));
}
function buildBodyGeo() {
  // manteau : moitié basse sombre, moitié haute + épaules en blanc (→ instanceColor = couleur par habitant)
  const coat_lo   = new THREE.CylinderGeometry(0.14, 0.17, 0.225, 5); coat_lo.translate(0, 0.1125, 0); habFillColors(coat_lo,   "#2a2730");
  const coat_hi   = new THREE.CylinderGeometry(0.11, 0.14, 0.225, 5); coat_hi.translate(0, 0.3375, 0); habFillColors(coat_hi,   "#ffffff");
  const hood      = new THREE.IcosahedronGeometry(0.13, 0);            hood.translate(0, 0.57, 0);      habFillColors(hood,      "#38303e");
  const shoulders = new THREE.BoxGeometry(0.38, 0.07, 0.20);          shoulders.translate(0, 0.43, 0);  habFillColors(shoulders, "#ffffff");
  const armL      = new THREE.BoxGeometry(0.065, 0.18, 0.09);         armL.translate(-0.175, 0.32, 0);  habFillColors(armL,      "#2a2730");
  const armR      = new THREE.BoxGeometry(0.065, 0.18, 0.09);         armR.translate( 0.175, 0.32, 0);  habFillColors(armR,      "#2a2730");
  for (const g of [coat_lo, coat_hi, hood, shoulders, armL, armR]) {
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal" && k !== "color") g.deleteAttribute(k);
    if (!g.index) g.setIndex([...Array(g.attributes.position.count).keys()]);
  }
  return mergeGeometries([coat_lo, coat_hi, hood, shoulders, armL, armR]);
}
const SCARF_PALETTE = ["#c44030","#c87828","#4a8c58","#4878c4","#9448c4","#c44888","#28a8c8","#b83020","#2858d4","#d45020","#407848","#c82868"];
const people = new THREE.InstancedMesh(buildBodyGeo(), new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true }), PEOPLE_MAX);
people.castShadow = true;
people.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
people.frustumCulled = false;
for (let i = 0; i < PEOPLE_MAX; i++) people.setColorAt(i, new THREE.Color(SCARF_PALETTE[i % SCARF_PALETTE.length]));
if (people.instanceColor) people.instanceColor.needsUpdate = true;
scene.add(people);

// lanternes : InstancedMesh séparé, visible la nuit (icosaèdre émissif)
const lanternMesh = new THREE.InstancedMesh(
  stripGeometry(new THREE.IcosahedronGeometry(0.1, 0)),
  new THREE.MeshBasicMaterial({ color: "#ff9440" }),
  PEOPLE_MAX);
lanternMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
lanternMesh.frustumCulled = false;
scene.add(lanternMesh);

// caisses portées : InstancedMesh séparé, uniquement pour les porteurs
const boxMesh = new THREE.InstancedMesh(
  (() => { const g = new THREE.BoxGeometry(0.22, 0.2, 0.22); for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal") g.deleteAttribute(k); return g; })(),
  new THREE.MeshLambertMaterial({ color: "#8b6a3a", flatShading: true }),
  PEOPLE_MAX);
boxMesh.castShadow = true;
boxMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
boxMesh.frustumCulled = false;
scene.add(boxMesh);

const walkers = Array.from({ length: PEOPLE_MAX }, (_, i) => ({
  ring: i % 7 === 0, path: i % 7, t: Math.random(), dir: Math.random() < 0.5 ? 1 : -1,
  speed: 0.50 + Math.random() * 0.25, side: (Math.random() - 0.5) * 0.45, phase: Math.random() * 6,
}));
// les chemins sont donnés en coordonnées Blender (x, y); dans la page: (x, -y) sur le sol
const toWorld = (r, a, out) => out.set(r * Math.cos(a), 0.06, -r * Math.sin(a));
const wPos = new THREE.Vector3(), wNext = new THREE.Vector3(), wSide = new THREE.Vector3(), wFwd = new THREE.Vector3(), wAux = new THREE.Vector3();

function updatePeople(dt) {
  const n = Math.min(PEOPLE_MAX, Math.round(mix.outside * (1 - mix.shelterK)));
  if (!layout || n === 0) { people.count = lanternMesh.count = boxMesh.count = 0; return; }
  const { paths, path_start: r0, ring } = layout;
  const shrinkK = Math.max(mix.sprintK, mix.shelterK); // sprint ou abri : chemins se rétractent vers la centrale
  const gather = habCfg.gather_span || 2.5;           // largeur minimale du rassemblement autour de la centrale
  let lanternN = 0, boxN = 0;
  for (let i = 0; i < n; i++) {
    const w = walkers[i];
    const isCarrier = i < habCarrierCount;
    // porteurs : chemin 1 ou 2 (direction cave/atelier), vitesse réduite
    const spd = isCarrier ? w.speed * 0.75 : w.speed;
    if (w.ring && ring && !isCarrier) {
      w.t += (w.dir * spd * dt) / (2 * Math.PI * ring);
      const r = Math.max(r0 + gather * 0.5, ring * (1 - shrinkK * 0.85)); // jamais à l'intérieur de la centrale
      const a = w.t * 2 * Math.PI;
      toWorld(r, a, wPos);
      toWorld(r, a + w.dir * 0.05, wNext);
    } else {
      const k = (isCarrier ? (i % 2 === 0 ? 1 : 2) : w.path) % paths.length;
      const r1base = layout.path_ends?.[k] ?? layout.path_end;
      const span = Math.max(gather, (r1base - r0) * (1 - shrinkK));
      const r1 = r0 + span;
      w.t += (w.dir * spd * dt) / span;
      if (w.t > 1 || w.t < 0) { w.dir *= -1; w.t = Math.min(Math.max(w.t, 0), 1); }
      const a = paths[k], r = r0 + (r1 - r0) * w.t;
      toWorld(r, a, wPos).add(wSide.set(Math.sin(a), 0, Math.cos(a)).multiplyScalar(w.side));
      toWorld(r + w.dir * 0.5, a, wNext);
    }
    wPos.y += Math.abs(Math.sin((performance.now() / 1000) * 7 * w.speed + w.phase)) * 0.05;
    tmpQ.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, Math.atan2(wNext.x - wPos.x, wNext.z - wPos.z));
    people.setMatrixAt(i, tmpM.compose(wPos, tmpQ, tmpS.setScalar(1)));
    // lanterne : visible uniquement la nuit
    const nightK = 1 - mix.day;
    if (nightK > 0.01) {
      wAux.copy(wPos).setY(wPos.y + 1.0);
      lanternMesh.setMatrixAt(lanternN++, tmpM.compose(wAux, tmpQ, tmpS.setScalar(nightK * 0.5)));
    }
    // caisse portée : premiers habCarrierCount habitants
    if (i < habCarrierCount) {
      wFwd.set(0, 0, 1).applyQuaternion(tmpQ);
      wAux.copy(wPos).addScaledVector(wFwd, 0.22).setY(wPos.y + 0.3);
      boxMesh.setMatrixAt(boxN++, tmpM.compose(wAux, tmpQ, tmpS.setScalar(1)));
    }
  }
  people.count = n;
  lanternMesh.count = lanternN;
  boxMesh.count = boxN;
  people.instanceMatrix.needsUpdate = true;
  if (lanternN > 0) lanternMesh.instanceMatrix.needsUpdate = true;
  if (boxN > 0) boxMesh.instanceMatrix.needsUpdate = true;
}

function updateInfra(s, snap = false) {
  const stages = s.infra_cfg || [];
  const tw = s.total_work || 0;
  for (const stage of stages) {
    for (const name of (stage.show || [])) {
      const entry = infraState.get(name);
      if (!entry) {
        if (!infraMissingWarned.has(name)) {
          infraMissingWarned.add(name);
          console.warn(`[TLW] stade infra "${name}" absent du GLB — objet 3D manquant`);
        }
        continue;
      }
      const t = tw < stage.wu ? 0 : tw >= stage.wu_to ? 1 : (tw - stage.wu) / (stage.wu_to - stage.wu);
      entry.target = t > 0 ? Math.max(0.001, Math.min(1, t)) : 0;
      if (snap) entry.current = entry.target;
      entry.obj.visible = entry.current > 0.001 || entry.target > 0.001;
    }
    for (const name of (stage.hide || [])) {
      const entry = infraState.get(name);
      if (!entry) continue;
      const t = tw < stage.wu ? 1 : !stage.wu_to || tw >= stage.wu_to ? 0
        : 1 - (tw - stage.wu) / (stage.wu_to - stage.wu);
      entry.target = Math.max(0, Math.min(1, t));
      if (snap) entry.current = entry.target;
      entry.obj.visible = entry.current > 0.001 || entry.target > 0.001;
    }
  }
}

// ------------------------------------------------- état de la simulation ---
const sim = { phase: "night", frozen: false, frost: 0, weather: "snow", rpm: 0, active: false, population: 0, heatK: 0, sprinting: false };
const mix = { day: 0, frozen: 0, frost: 0, white: 0, fogK: 1, snow: 0.5, wind: 1, outside: 0, wheelSpeed: 0, sprintK: 0, shelterK: 0 };
const infraState = new Map(); // name → { obj, current, target } — infra progressive + supply
const infraMissingWarned = new Set(); // noms de stades absents du GLB, avertis une seule fois
let infraSnapped = false;     // snap sur le premier applyState après chargement du GLB
let lastState = null;
const cA = new THREE.Color(), cB = new THREE.Color(), cC = new THREE.Color();

const needsShelter = () => sim.phase !== "day" || sim.weather === "blizzard" || sim.frozen;

function applyState(s) {
  const firstState = lastState === null;
  lastState = s;
  if (s.inhabitants_cfg) Object.assign(habCfg, s.inhabitants_cfg);
  const frac = s.built?.workshop ? (habCfg.carrier_fraction_workshop || 0.25)
             : s.built?.cellar   ? (habCfg.carrier_fraction_cellar   || 0.15)
             : 0;
  habCarrierCount = Math.floor((s.population || 0) * frac);
  Object.assign(sim, {
    phase: s.phase, frozen: s.frozen, frost: s.frost, weather: s.weather || "snow",
    rpm: s.hamster.rpm || 0, active: s.hamster.active, sprinting: s.hamster.sprinting || false, population: s.population,
    heatK: s.frozen ? 0 : Math.min((s.hamster.rpm || 0) / 100000, 1),
  });
  if (firstState) mix.shelterK = needsShelter() ? 1 : 0; // au chargement, pas de sortie/rentrée fantôme
  if (cityReady) {
    for (const [id, list] of Object.entries(buildings)) {
      const count = (s.built || {})[id] || 0;
      const inProgress = s.project && s.project.id === id;
      list.forEach((inst, j) => {
        const mode = j < count ? "built" : inProgress && j === count ? "construction" : "hidden";
        setBuildingMode(inst, mode, inProgress ? s.project.pct : 0);
      });
    }
    updateInfra(s, !infraSnapped);
    infraSnapped = true;
  }
}

const ease = (cur, target, dt, speed) => cur + (target - cur) * (1 - Math.exp(-speed * dt));

function updateLook(dt) {
  const W = WEATHER[sim.weather] || WEATHER.snow;
  mix.day = ease(mix.day, sim.phase === "day" && !sim.frozen ? 1 : 0, dt, 0.6);
  mix.frozen = ease(mix.frozen, sim.frozen ? 1 : 0, dt, 0.4);
  mix.frost = ease(mix.frost, sim.frost, dt, 0.5);
  mix.white = ease(mix.white, W.white, dt, 0.5);
  mix.fogK = ease(mix.fogK, W.fog, dt, 0.5);
  mix.snow = ease(mix.snow, Math.min(1, W.snow + (sim.frozen ? 0.25 : 0)), dt, 0.8);
  mix.wind = ease(mix.wind, W.wind, dt, 0.5);
  mix.sprintK = ease(mix.sprintK, sim.sprinting ? 1 : 0, dt, 0.3);
  // abri : nuit, blizzard ou hibernation → chemins se rétractent puis habitants disparaissent
  const fastShelter = sim.weather === "blizzard" || sim.frozen;
  const fadeS = fastShelter ? (habCfg.fade_blizzard_s || 5) : (habCfg.fade_to_shelter_s || 14);
  mix.shelterK = ease(mix.shelterK, needsShelter() ? 1 : 0, dt, 1 / fadeS);
  // nombre d'habitants dehors selon la météo ; nuit et abri passent par shelterK (voir updatePeople) :
  // ils rentrent et sortent un par un, jamais tous d'un coup sur la centrale
  const outsideFactor = sim.frozen ? 0 : W.outside;
  mix.outside = ease(mix.outside, Math.min(sim.population, PEOPLE_MAX) * outsideFactor, dt, 0.6);

  // ciel et brouillard
  const skyBase = cA.set(LOOK.night.sky).lerp(cB.set(LOOK.day.sky), mix.day).lerp(cC.set(LOOK.frozen.sky), mix.frozen);
  const skyWhiteK = mix.white * (0.5 + 0.5 * mix.day);
  scene.background.copy(skyBase).lerp(WHITEOUT, skyWhiteK);
  // Le brouillard blanchit davantage que le ciel selon la densité météo (mix.fogK)
  const fogWhiteK = Math.min(1, skyWhiteK + Math.max(0, mix.fogK - 1) * 0.35);
  scene.fog.color.copy(skyBase).lerp(WHITEOUT, fogWhiteK);
  const fogBase = THREE.MathUtils.lerp(LOOK.night.fog, LOOK.day.fog, mix.day) + mix.frozen * 0.004;
  // en dézoomant au-delà du cadrage de départ, le brouillard ne s'épaissit plus (sinon la ville se voile)
  const zoomK = Math.min(1, fogFit / Math.max(camera.position.distanceTo(controls.target), 1));
  scene.fog.density = fogBase * mix.fogK * fogScale * zoomK;

  // lumières
  sun.intensity = THREE.MathUtils.lerp(THREE.MathUtils.lerp(LOOK.night.sun, LOOK.day.sun, mix.day), LOOK.frozen.sun, mix.frozen) * (1 - 0.5 * mix.white);
  sun.color.set(LOOK.night.sunColor).lerp(cB.set(LOOK.day.sunColor), mix.day);
  hemi.intensity = THREE.MathUtils.lerp(THREE.MathUtils.lerp(LOOK.night.hemi, LOOK.day.hemi, mix.day), LOOK.frozen.hemi, mix.frozen);
  const pulse = 1 + 0.06 * Math.sin(performance.now() / 1000 * (1.5 + 4 * sim.heatK));
  heat.intensity = (1 - mix.frozen) * (38 + 70 * sim.heatK) * pulse;

  // matériaux lumineux
  if (emissive.fire) emissive.fire.mat.emissiveIntensity = emissive.fire.base * (0.08 + 0.92 * (1 - mix.frozen)) * (0.7 + 0.6 * sim.heatK) * pulse;
  if (emissive.window) emissive.window.mat.emissiveIntensity = emissive.window.base * (1 - mix.frozen * 0.92) * (0.45 + 0.55 * (1 - mix.day));
  // la serre brille doucement le jour et plus la nuit (sinon le halo la blanchit : elle éblouissait)
  if (emissive.greenhouse) emissive.greenhouse.mat.emissiveIntensity = emissive.greenhouse.base * (1 - mix.frozen * 0.9) * (0.35 + 0.3 * (1 - mix.day));

  // le givre recouvre la ville
  const rime = Math.min(1, mix.frost * 0.7 + mix.frozen * 0.12);
  cA.set("#dfe9f7");
  for (const t of tinted) t.mat.color.copy(t.base).lerp(cA, rime);
  $("frost").style.opacity = Math.min(1, mix.frost * 1.1 + mix.frozen * 0.3).toFixed(3);
  if (bloom) bloom.strength = 0.45 + 0.35 * (1 - mix.day) * (1 - mix.frozen);
}

// --------------------------------------------------------------- boucle ---
const clock = new THREE.Clock();
let fpsAcc = 0, fpsFrames = 0, slowSeconds = 0;

function frame() {
  const raw = clock.getDelta();
  const dt = Math.min(raw, 0.1);   // particules: pas de saut après une pause
  const dtLook = Math.min(raw, 1); // ambiance: même rythme sur une machine lente
  if (!reduced && performance.now() - lastInteraction > 9000) controls.autoRotate = true;
  controls.update();
  updateLook(dtLook);
  if (wheel) { // la Roue tourne à la vraie vitesse du hamster (tours/min)
    mix.wheelSpeed = ease(mix.wheelSpeed, sim.active ? sim.rpm / 1000 : 0, dtLook, 1.5);
    wheel.rotation.z -= (mix.wheelSpeed / 60) * 2 * Math.PI * dt * (reduced ? 0.2 : 1);
  }
  updateSmoke(dt, mix.wind);
  updateSnow(dt, mix.snow, mix.wind);
  updatePeople(dt);
  for (const b of instances) {
    if (b.pop < 1) { b.pop = Math.min(1, b.pop + dt * 1.4); const k = 1 - Math.pow(1 - b.pop, 3); b.group.scale.setScalar(0.82 + 0.18 * k); }
  }
  for (const entry of infraState.values()) {
    if (entry.current === entry.target) continue;
    entry.current = ease(entry.current, entry.target, dt, 1.5);
    if (Math.abs(entry.current - entry.target) < 0.001) entry.current = entry.target;
    entry.obj.scale.setScalar(Math.max(0.001, entry.current));
    entry.obj.visible = entry.current > 0.001;
  }
  if (composer) composer.render(); else renderer.render(scene, camera);
  watchPerformance(dt);
  requestAnimationFrame(frame);
}

// si la machine rame, on retire le halo puis on baisse la résolution
const perfEl = new URLSearchParams(location.search).has("perf") ? document.createElement("div") : null;
if (perfEl) {
  perfEl.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:9;font:11px/1.4 monospace;color:#fff;background:rgba(0,0,0,.65);padding:4px 7px;white-space:pre;pointer-events:none";
  document.body.appendChild(perfEl);
}

function watchPerformance(dt) {
  fpsAcc += dt; fpsFrames++;
  if (fpsAcc < 1) return;
  const fps = fpsFrames / fpsAcc;
  if (perfEl) perfEl.textContent = `${fps.toFixed(0)} i/s · ${mobile ? "mobile" : "PC"}\n×${renderer.getPixelRatio()} · ${composer ? "halo" : "sans halo"}\n${people.count} hab.\nbrume ${scene.fog.density.toFixed(4)} · d ${camera.position.distanceTo(controls.target).toFixed(0)}/${controls.maxDistance.toFixed(0)} · v3`;
  fpsAcc = 0; fpsFrames = 0;
  slowSeconds = fps < 28 ? slowSeconds + 1 : 0;
  if (slowSeconds < 3) return;
  slowSeconds = 0;
  if (composer) { composer = null; bloom = null; }
  else if (renderer.getPixelRatio() > 1) { renderer.setPixelRatio(1); resize(); }
}

function resize() {
  const box = $("view").getBoundingClientRect();
  const w = Math.max(box.width, 1), h = Math.max(box.height, 1);
  renderer.setSize(w, h, false);
  if (composer) { composer.setSize(w, h); }
  camera.aspect = w / h;
  // recule la caméra pour que la ville tienne en largeur, même sur un écran étroit
  const hfov = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect);
  const fit = Math.max(46, 20 / Math.tan(hfov / 2));
  fogScale = Math.min(1, 46 / fit) * (mobile ? 0.75 : 1); // téléphone: pas de halo, on garde plus de netteté
  fogFit = fit;
  controls.maxDistance = fit * 1.45;
  camera.updateProjectionMatrix();
  return fit;
}
new ResizeObserver(resize).observe($("view"));
{
  const fit = resize();
  const phi = 0.98, theta = 0.42;
  camera.position.set(Math.sin(phi) * Math.sin(theta), Math.cos(phi), Math.sin(phi) * Math.cos(theta))
    .multiplyScalar(fit).add(controls.target);
}

// ---------------------------------------------- survol: nom du bâtiment ---
const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
function pick(ev) {
  if (!cityReady) return;
  const r = renderer.domElement.getBoundingClientRect();
  pointer.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const targets = instances.filter((b) => b.mode !== "hidden").flatMap((b) => b.meshes);
  const hit = ray.intersectObjects(targets, false).find((h) => h.object.userData.instance);
  const tip = $("tip");
  if (!hit) { tip.hidden = true; return; }
  const b = hit.object.userData.instance;
  tip.textContent = b.mode === "built" ? cap(b.name) : `${cap(b.name)}, under construction`;
  tip.style.left = `${ev.clientX - r.left}px`;
  tip.style.top = `${ev.clientY - r.top}px`;
  tip.hidden = false;
}
renderer.domElement.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse") pick(e); });
renderer.domElement.addEventListener("click", pick);
renderer.domElement.addEventListener("pointerleave", () => { $("tip").hidden = true; });

if (new URLSearchParams(location.search).has("debug")) window.__tlw = { people, mix, scene, camera, controls, sim, buildings, applyState };

// ------------------------------------------------------------- démarrage ---
export function start() {
  startHud({
    onState: applyState,
    onFirstState: (st) => buildCity(st.catalog).catch((err) => {
      console.error(err);
      fallback("The 3D town could not be loaded. This is a still picture of it.");
    }),
  });
}
