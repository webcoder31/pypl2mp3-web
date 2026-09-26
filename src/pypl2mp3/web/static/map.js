/* The library as a cloud, one point per song.
 *
 * Position comes from the sound and colour from the genre Shazam gave
 * it. Two independent sources on purpose: if the colours clump, the
 * vectors caught something real; if they are peppered evenly through
 * the cloud, they did not. The picture checks itself, which is the same
 * job scripts/measure_similarity.py does on a number.
 *
 * A module, and the only one here: it is the one thing on the page that
 * needs an import, and console.js stays the plain script it has always
 * been. It reaches console.js the way anything else would — by clicking
 * the row the song already has — so neither knows about the other.
 *
 * Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
 * License: CeCILL-C (http://www.cecill.info)
 */

import * as THREE from "three";
import { OrbitControls } from "/static/three-orbit.js";

const frame = document.getElementById("map-frame");
const canvas = document.getElementById("map-canvas");
const note = document.getElementById("map-note");
const legend = document.getElementById("map-legend");
const readout = document.getElementById("map-hover");

// Twelve, and a grey for everything else. Read from the stylesheet
// rather than written here, so the map turns with the theme like the
// rest of the page.
function palette() {
  const style = getComputedStyle(document.documentElement);
  const out = [];

  for (let at = 1; at <= 12; at++) {
    out.push(style.getPropertyValue("--map-" + at).trim() || "#888");
  }

  return { lit: out, dim: style.getPropertyValue("--map-dim").trim() || "#555" };
}

let drawn = null;
let points = [];
let asked = null;

// One renderer for the life of the page, and not one per drawing.
//
// A canvas holds a single WebGL context and a browser grants a page
// only so many — Chrome drops the oldest at about sixteen and then
// refuses. Building a fresh renderer every time the selection changed
// leaked one each time, and the map eventually stopped opening with
// "could not create a WebGL context" on a machine where it had been
// working all along.
let renderer = null;

// Remembered whether it worked *or not*. Caching only the success left
// every later selection asking again on a browser that cannot answer,
// and three.js logs a paragraph each time: four attempts, four walls of
// text, for one thing that was settled on the first.
let refused = null;

function canvasRenderer() {
  if (renderer) return renderer;
  if (refused) throw refused;

  try {
    renderer = new THREE.WebGLRenderer({
      canvas: canvas, antialias: true, alpha: true,
    });
  } catch (error) {
    refused = error;
    throw error;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  return renderer;
}

// Why it will not draw, in words that say what to do about it. "This
// browser will not open a 3D canvas" is true of a GPU switched off, of
// a blocklisted driver and of a page that has run out of contexts, and
// those want three different things from the reader.
function whyNot(error) {
  let context = null;
  try {
    context = canvas.getContext("webgl2") || canvas.getContext("webgl");
  } catch (ignored) {
    context = null;
  }

  if (context) {
    return "The 3D canvas opened but the map could not be built: "
      + (error && error.message ? error.message : String(error));
  }

  return "This browser will not open a 3D canvas, so the map cannot be "
    + "drawn. chrome://gpu says whether hardware acceleration is off or "
    + "the driver is blocklisted. Everything else on the page works "
    + "without it.";
}

function filters() {
  const form = document.getElementById("filters");
  if (!form) return "";

  const said = new URLSearchParams(new FormData(form));
  // The map is the whole selection, in no order: the play order decides
  // what comes after what, and nothing here comes after anything.
  said.delete("order");
  said.delete("start");

  return said.toString();
}

async function draw() {
  const wanted = filters();
  if (drawn && asked === wanted) {
    drawn.resize();
    return;
  }

  note.textContent = "Placing " + (points.length || "the") + " songs…";
  note.hidden = false;

  const answer = await fetch("/map/points?" + wanted);
  const said = await answer.json();

  asked = wanted;
  points = said.points;

  if (drawn) drawn.dispose();

  try {
    drawn = build(said);
  } catch (error) {
    // No WebGL: a machine with it switched off, a browser refusing it
    // over a remote desktop, an automation Chrome whose GPU process
    // will not boot. The cloud is a few hundred discs and a rotation
    // matrix, so it does not need one — this draws the same picture on
    // a plain 2D canvas, which is the context every browser has.
    console.info("map: " + whyNot(error) + " Drawing it flat instead.");
    drawn = buildFlat(said);
  }

  note.hidden = true;
  showLegend(said.genres);
}

function build(said) {
  const colours = palette();
  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(
    55, frame.clientWidth / frame.clientHeight, 0.1, 2000
  );

  const renderer = canvasRenderer();

  // Where the cloud is and how big, so the camera frames it whatever
  // the relaxation settled on rather than at a distance written here.
  const middle = new THREE.Vector3();
  said.points.forEach(function (one) {
    middle.add(new THREE.Vector3(one.at[0], one.at[1], one.at[2]));
  });
  middle.divideScalar(Math.max(1, said.points.length));

  let reach = 1;
  const places = new Float32Array(said.points.length * 3);
  const shades = new Float32Array(said.points.length * 3);
  const tint = new THREE.Color();

  said.points.forEach(function (one, at) {
    places[at * 3] = one.at[0];
    places[at * 3 + 1] = one.at[1];
    places[at * 3 + 2] = one.at[2];

    reach = Math.max(reach, middle.distanceTo(
      new THREE.Vector3(one.at[0], one.at[1], one.at[2])
    ));

    tint.set(one.shade >= 0 ? colours.lit[one.shade] : colours.dim);
    shades[at * 3] = tint.r;
    shades[at * 3 + 1] = tint.g;
    shades[at * 3 + 2] = tint.b;
  });

  const cloud = new THREE.BufferGeometry();
  cloud.setAttribute("position", new THREE.BufferAttribute(places, 3));
  cloud.setAttribute("color", new THREE.BufferAttribute(shades, 3));

  // One object for the whole library, not one per song: 944 meshes is
  // 944 draw calls, and this is one.
  const dots = new THREE.Points(cloud, new THREE.PointsMaterial({
    size: reach * 0.018,
    vertexColors: true,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.9,
  }));
  scene.add(dots);

  camera.position.copy(middle).add(new THREE.Vector3(0, 0, reach * 2.6));
  camera.lookAt(middle);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(middle);
  controls.enableDamping = true;
  controls.update();

  // What the pointer is over. A cloud of points needs a threshold in
  // world units, because a point has no surface to hit.
  const finder = new THREE.Raycaster();
  finder.params.Points.threshold = reach * 0.02;
  const pointer = new THREE.Vector2();
  let over = -1;

  function look(event) {
    const box = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - box.left) / box.width) * 2 - 1;
    pointer.y = -((event.clientY - box.top) / box.height) * 2 + 1;

    finder.setFromCamera(pointer, camera);
    const hit = finder.intersectObject(dots, false)[0];

    over = hit ? hit.index : -1;
    readout.textContent = over >= 0 ? said.points[over].label : "";
    renderer.domElement.style.cursor = over >= 0 ? "pointer" : "grab";
  }

  function play() {
    if (over < 0) return;

    // Through the row the song already has, so the map does not need to
    // know what a queue is — and clicking a point does exactly what
    // clicking a row does, because it *is* clicking a row.
    const key = said.points[over].key;
    const row = document.querySelector(
      '#list tr[data-song-key="' + key + '"]'
    );
    if (row) row.click();
  }

  renderer.domElement.addEventListener("pointermove", look);
  renderer.domElement.addEventListener("click", play);

  function resize() {
    const wide = frame.clientWidth;
    const tall = frame.clientHeight;
    if (!wide || !tall) return;

    renderer.setSize(wide, tall, false);
    camera.aspect = wide / tall;
    camera.updateProjectionMatrix();
  }

  let running = true;

  function turn() {
    if (!running) return;
    controls.update();
    renderer.render(scene, camera);
    window.requestAnimationFrame(turn);
  }

  resize();
  turn();

  return {
    resize: resize,
    dispose: function () {
      running = false;
      renderer.domElement.removeEventListener("pointermove", look);
      renderer.domElement.removeEventListener("click", play);
      controls.dispose();
      scene.remove(dots);
      cloud.dispose();
      dots.material.dispose();
      // The renderer itself stays: it owns the one context this page
      // gets, and throwing it away is what exhausted them.
    },
  };
}

// The same cloud, drawn with arcs.
//
// A point cloud asks a renderer for very little: a rotation, a
// projection, a depth order and a filled circle each. WebGL gives size
// attenuation and antialiasing for nothing; here the first is one
// division and the second is what `arc` does anyway.
//
// Redrawn on demand and not in an animation loop. Every frame is
// rasterised by the processor on the machine this was written for, and
// a still cloud asking for sixty of them a second would spend a core on
// a picture that is not changing.
function buildFlat(said) {
  const colours = palette();

  // A canvas that has been asked for a WebGL context and refused is not
  // one to ask for a 2D one. A clone carries the id, the class and the
  // place in the page, and has been asked for nothing.
  const fresh = canvas.cloneNode(false);
  canvas.replaceWith(fresh);

  const paper = fresh.getContext("2d");

  const middle = [0, 0, 0];
  said.points.forEach(function (one) {
    middle[0] += one.at[0];
    middle[1] += one.at[1];
    middle[2] += one.at[2];
  });
  const count = Math.max(1, said.points.length);
  middle[0] /= count;
  middle[1] /= count;
  middle[2] /= count;

  let reach = 1;
  const cloud = said.points.map(function (one, at) {
    const x = one.at[0] - middle[0];
    const y = one.at[1] - middle[1];
    const z = one.at[2] - middle[2];

    reach = Math.max(reach, Math.sqrt(x * x + y * y + z * z));

    return {
      at: at,
      x: x, y: y, z: z,
      tint: one.shade >= 0 ? colours.lit[one.shade] : colours.dim,
    };
  });

  // Where the eye is: far enough that the whole cloud fits the frame,
  // and turned by whatever the pointer has dragged.
  let yaw = 0.4;
  let pitch = 0.2;
  // A sphere of radius `reach` fills a 55-degree frame from
  // reach / sin(27.5°) = 2.17 away; a little further leaves a margin.
  // Copied from the WebGL camera it came from, 3.2 put the cloud in the
  // middle third of the frame and left the rest empty.
  let away = reach * 2.4;
  let over = -1;

  // Scratch space for the drawing, so a redraw allocates nothing.
  const flat = cloud.map(function () {
    return { x: 0, y: 0, depth: 0, size: 0, tint: "", at: 0 };
  });

  function turn() {
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const cp = Math.cos(pitch);
    const sp = Math.sin(pitch);

    for (let i = 0; i < cloud.length; i++) {
      const one = cloud[i];

      // Around the upright axis, then tipped: the order the pointer
      // implies, dragging sideways to spin and up to look over.
      const x = one.x * cy + one.z * sy;
      const back = -one.x * sy + one.z * cy;
      const y = one.y * cp - back * sp;
      const z = one.y * sp + back * cp;

      const seen = flat[i];
      seen.depth = z + away;
      seen.x = x;
      seen.y = y;
      seen.tint = one.tint;
      seen.at = one.at;
    }
  }

  function paint() {
    const wide = fresh.width;
    const tall = fresh.height;
    if (!wide || !tall) return;

    // 55 degrees, as the WebGL camera had.
    const lens = (tall / 2) / Math.tan((55 * Math.PI / 180) / 2);
    const middleX = wide / 2;
    const middleY = tall / 2;
    const dot = Math.max(1.5, reach * 0.022 * lens / away);

    paper.clearRect(0, 0, wide, tall);

    // Far to near, so the near ones cover what is behind them — which
    // is the whole of what a depth buffer was doing.
    const order = flat.slice().sort(function (a, b) {
      return b.depth - a.depth;
    });

    for (let i = 0; i < order.length; i++) {
      const seen = order[i];
      if (seen.depth <= 0.1) continue;

      const scale = lens / seen.depth;
      const x = middleX + seen.x * scale;
      const y = middleY - seen.y * scale;
      // One division is the whole of size attenuation.
      const size = Math.max(0.8, dot * away / seen.depth);

      paper.beginPath();
      paper.arc(x, y, size, 0, Math.PI * 2);
      paper.fillStyle = seen.tint;
      paper.globalAlpha = seen.at === over ? 1 : 0.9;
      paper.fill();

      if (seen.at === over) {
        paper.globalAlpha = 1;
        paper.lineWidth = 1.5;
        paper.strokeStyle = seen.tint;
        paper.beginPath();
        paper.arc(x, y, size + 3.5, 0, Math.PI * 2);
        paper.stroke();
      }
    }

    paper.globalAlpha = 1;
  }

  function redraw() {
    turn();
    paint();
  }

  function whereIs(event) {
    const box = fresh.getBoundingClientRect();
    const ratio = fresh.width / box.width;
    return {
      x: (event.clientX - box.left) * ratio,
      y: (event.clientY - box.top) * ratio,
      ratio: ratio,
    };
  }

  function nearest(spot) {
    const lens = (fresh.height / 2) / Math.tan((55 * Math.PI / 180) / 2);
    const middleX = fresh.width / 2;
    const middleY = fresh.height / 2;
    // Eight CSS pixels, in the canvas's own units.
    const reachable = (8 * spot.ratio) ** 2;

    let found = -1;
    let closest = reachable;
    let front = Infinity;

    for (let i = 0; i < flat.length; i++) {
      const seen = flat[i];
      if (seen.depth <= 0.1) continue;

      const scale = lens / seen.depth;
      const dx = middleX + seen.x * scale - spot.x;
      const dy = middleY - seen.y * scale - spot.y;
      const gap = dx * dx + dy * dy;

      // The nearest to the pointer, and among equals the nearest to the
      // eye: two points under the cursor means the one in front.
      if (gap <= closest && (gap < closest || seen.depth < front)) {
        closest = gap;
        front = seen.depth;
        found = seen.at;
      }
    }

    return found;
  }

  let dragging = null;
  // Where the drag began, kept apart from where it has got to: the
  // second is updated on every move so that the turning is
  // incremental, and comparing against it at the end measured the last
  // pixel instead of the journey — so every drag ended in a click and
  // played whatever it happened to stop over.
  let began = null;

  function look(event) {
    if (dragging) {
      const spot = whereIs(event);
      yaw += (spot.x - dragging.x) * 0.006 / spot.ratio;
      pitch += (spot.y - dragging.y) * 0.006 / spot.ratio;
      // Stopped short of the poles, where the cloud would flip over.
      pitch = Math.max(-1.45, Math.min(1.45, pitch));
      dragging = spot;
      redraw();
      return;
    }

    const was = over;
    over = nearest(whereIs(event));

    if (over !== was) {
      readout.textContent = over >= 0 ? said.points[over].label : "";
      fresh.style.cursor = over >= 0 ? "pointer" : "grab";
      paint();
    }
  }

  function grab(event) {
    dragging = whereIs(event);
    began = dragging;
    fresh.setPointerCapture(event.pointerId);
  }

  function letGo(event) {
    const spot = whereIs(event);
    const spun = began && (
      Math.abs(spot.x - began.x) > 3 || Math.abs(spot.y - began.y) > 3
    );
    dragging = null;
    began = null;

    // A drag that turned the cloud is not a click on what it ended
    // over: letting it play a song would make the map unturnable.
    if (spun || over < 0) return;

    const row = document.querySelector(
      '#list tr[data-song-key="' + said.points[over].key + '"]'
    );
    if (row) row.click();
  }

  function roll(event) {
    event.preventDefault();
    away *= event.deltaY > 0 ? 1.1 : 1 / 1.1;
    away = Math.max(reach * 1.2, Math.min(reach * 12, away));
    redraw();
  }

  fresh.addEventListener("pointermove", look);
  fresh.addEventListener("pointerdown", grab);
  fresh.addEventListener("pointerup", letGo);
  fresh.addEventListener("wheel", roll, { passive: false });

  function resize() {
    const wide = frame.clientWidth;
    const tall = frame.clientHeight;
    if (!wide || !tall) return;

    const ratio = Math.min(window.devicePixelRatio, 2);
    fresh.width = Math.round(wide * ratio);
    fresh.height = Math.round(tall * ratio);
    redraw();
  }

  resize();

  return {
    resize: resize,
    dispose: function () {
      fresh.removeEventListener("pointermove", look);
      fresh.removeEventListener("pointerdown", grab);
      fresh.removeEventListener("pointerup", letGo);
      fresh.removeEventListener("wheel", roll);
    },
  };
}

function showLegend(genres) {
  const colours = palette();

  legend.replaceChildren();
  genres.forEach(function (name, at) {
    const one = document.createElement("span");
    one.className = "map-genre";
    one.innerHTML = '<span class="map-pip"></span>';
    one.firstChild.style.background = colours.lit[at];
    one.append(name);
    legend.append(one);
  });

  const rest = document.createElement("span");
  rest.className = "map-genre";
  rest.innerHTML = '<span class="map-pip"></span>';
  rest.firstChild.style.background = colours.dim;
  rest.append("everything else");
  legend.append(rest);
}

// Only when the tab is opened, and only once per selection: placing 944
// songs is two seconds of numpy, and nobody asked for it by loading the
// page.
new MutationObserver(function () {
  if (document.body.dataset.tab === "map") draw();
}).observe(document.body, { attributeFilter: ["data-tab"] });

window.addEventListener("resize", function () {
  if (drawn) drawn.resize();
});
