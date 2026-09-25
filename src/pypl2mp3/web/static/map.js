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

function canvasRenderer() {
  if (renderer) return renderer;

  renderer = new THREE.WebGLRenderer({
    canvas: canvas, antialias: true, alpha: true,
  });
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
    // over a remote desktop, an automation Chrome with the GPU
    // disabled. Say so — an empty frame and a rejected promise in the
    // console look exactly like a page that is still loading.
    drawn = null;
    asked = null;
    note.textContent = whyNot(error);
    note.hidden = false;
    return;
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
