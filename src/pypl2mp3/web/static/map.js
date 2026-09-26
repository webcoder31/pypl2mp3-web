/* The library as a cloud, one point per song.
 *
 * Position comes from the sound and colour from the genre Shazam gave
 * it. Two independent sources on purpose: if the colours clump, the
 * vectors caught something real; if they are peppered evenly through
 * the cloud, they did not. The picture checks itself, which is the same
 * job scripts/measure_similarity.py does on a number.
 *
 * Drawn on a plain 2D canvas, which is the context every browser has.
 * A point cloud asks a renderer for very little — a rotation, a
 * projection, a depth order and a shaded circle each — and three.js
 * asked for 760 KB and a GPU in return. The GPU is what this was
 * written on and it has none: its Chrome cannot boot a GPU process at
 * all, so the WebGL version was never once watched running, while this
 * one showed up two defects in its first ten minutes.
 *
 * It reaches console.js the way anything else would — by clicking the
 * row the song already has — so neither knows about the other.
 *
 * Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
 * License: CeCILL-C (http://www.cecill.info)
 */


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

// What the listing is showing, as a query string: the map is of the
// selection, not of the library. Sliced out of the module by mistake
// when the other renderer went — which every test passed through and
// the first minute in a browser did not.
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
    drawn.showing(true);
    return;
  }

  note.textContent = "Placing " + (points.length || "the") + " songs…";
  note.hidden = false;

  const answer = await fetch("/map/points?" + wanted);
  const said = await answer.json();

  asked = wanted;
  points = said.points;

  if (drawn) drawn.dispose();

  drawn = build(said);

  note.hidden = true;
  showLegend(said.genres);
}

function build(said) {
  const colours = palette();

  const paper = canvas.getContext("2d");

  // One sphere per colour, shaded once into an offscreen canvas and
  // then stamped. Shading each point where it lands would build nine
  // hundred gradients a frame; this builds thirteen for the life of
  // the drawing, and a scaled drawImage is a blit.
  const SPRITE = 64;
  const balls = new Map();

  function ball(tint) {
    const pad = document.createElement("canvas");
    pad.width = SPRITE;
    pad.height = SPRITE;

    const ink = pad.getContext("2d");
    const middle = SPRITE / 2;

    ink.fillStyle = tint;
    ink.beginPath();
    ink.arc(middle, middle, middle - 0.5, 0, Math.PI * 2);
    ink.fill();

    // Lit inside the disc already drawn, so the colour stays the
    // genre's own and only the light on it is added — which is what
    // keeps the legend true. A rim that falls away to give the edge a
    // turn, and a highlight up and to the left, where a reader expects
    // the light to be coming from.
    //
    // Both are kept off the middle of the sphere on purpose. The first
    // pass darkened half the disc and spread a white film over nine
    // tenths of it, and the cloud came out dull: beside its own pip in
    // the legend every sphere was a paler thing.
    //
    // The shade is cast from where the light is, not from the centre. A
    // gradient concentric with the disc darkens the whole edge equally,
    // which on the light theme's white reads as a black outline drawn
    // round every point rather than as a sphere turning away. Centred
    // on the highlight instead, and reaching half again past the far
    // edge, it leaves the lit side clean and only the side facing away
    // is in shadow — which is what a sphere does.
    ink.globalCompositeOperation = "source-atop";

    const shade = ink.createRadialGradient(
      middle * 0.66, middle * 0.6, middle * 0.2,
      middle * 0.66, middle * 0.6, middle * 1.55
    );
    shade.addColorStop(0, "rgba(0, 0, 0, 0)");
    shade.addColorStop(0.45, "rgba(0, 0, 0, 0)");
    shade.addColorStop(0.8, "rgba(0, 0, 0, 0.1)");
    shade.addColorStop(1, "rgba(0, 0, 0, 0.32)");
    ink.fillStyle = shade;
    ink.fillRect(0, 0, SPRITE, SPRITE);

    const lit = ink.createRadialGradient(
      middle * 0.66, middle * 0.6, 0,
      middle * 0.66, middle * 0.6, middle * 0.52
    );
    lit.addColorStop(0, "rgba(255, 255, 255, 0.78)");
    lit.addColorStop(0.5, "rgba(255, 255, 255, 0.1)");
    lit.addColorStop(1, "rgba(255, 255, 255, 0)");
    ink.fillStyle = lit;
    ink.fillRect(0, 0, SPRITE, SPRITE);

    return pad;
  }

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

    const tint = one.shade >= 0 ? colours.lit[one.shade] : colours.dim;
    if (!balls.has(tint)) balls.set(tint, ball(tint));

    return {
      at: at,
      x: x, y: y, z: z,
      tint: tint,
      ball: balls.get(tint),
    };
  });

  // Where the eye is: far enough that the whole cloud fits the frame,
  // and turned by whatever the pointer has dragged.
  let yaw = 0.4;
  let pitch = 0.2;
  // A sphere of radius `reach` fills a 55-degree frame from
  // reach / sin(27.5°) = 2.17 away; a little further leaves a margin.
  // At 3.2, which is what the first camera here used, the cloud sat in
  // the middle third of the frame and the rest was empty.
  let away = reach * 2.4;

  // How big a song is, as a fraction of the cloud's own radius. Opaque
  // and small: nine hundred translucent discs over each other made a
  // haze where the eye wanted points, and the colours mixed into
  // something that was nobody's genre.
  const POINT = 0.011;
  let over = -1;

  // Scratch space for the drawing, so a redraw allocates nothing.
  const flat = cloud.map(function () {
    return { x: 0, y: 0, depth: 0, size: 0, tint: "", ball: null, at: 0 };
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
      seen.ball = one.ball;
      seen.at = one.at;
    }
  }

  function paint() {
    const wide = canvas.width;
    const tall = canvas.height;
    if (!wide || !tall) return;

    // 55 degrees: wide enough to hold the cloud, narrow enough that
    // the perspective still says which islands are in front.
    const lens = (tall / 2) / Math.tan((55 * Math.PI / 180) / 2);
    const middleX = wide / 2;
    const middleY = tall / 2;
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
      // One division is the whole of size attenuation — and a ceiling,
      // because flying into the cloud would otherwise fill the frame
      // with the one disc nearest the eye.
      const size = Math.min(
        18, Math.max(0.6, reach * POINT * lens / seen.depth)
      );

      paper.drawImage(seen.ball, x - size, y - size, size * 2, size * 2);

      if (seen.at === over) {
        paper.lineWidth = 1.5;
        paper.strokeStyle = seen.tint;
        paper.beginPath();
        paper.arc(x, y, size + 3.5, 0, Math.PI * 2);
        paper.stroke();
      }
    }

  }

  function redraw() {
    turn();
    paint();
  }

  // How the movement settles once the hand is off it.
  //
  // GLIDE is what is left of the spin each frame after the pointer lets
  // go. At 0.93 a hard flick was still turning nearly two seconds
  // later, which reads as the map having got away from you; 0.90 and a
  // floor five times higher stop it after about one.
  //
  // SPRING pulls the eye towards where the wheel asked it to be and
  // DAMP is what stops it — loose enough that it arrives about a tenth
  // past and comes back, which is the small bounce, and tight enough to
  // be done in twenty frames.
  const GLIDE = 0.90;
  const SPRING = 0.22;
  const DAMP = 0.62;

  // Somebody who has asked their system not to animate things has asked
  // for this too: the target is then simply where it goes.
  const stillness = window.matchMedia("(prefers-reduced-motion: reduce)");

  let wantAway = away;
  let zooming = 0;
  let turning = 0;
  let tipping = 0;

  // Left alone, the cloud turns and breathes.
  //
  // A still projection of a sphere is ambiguous — which islands are in
  // front is exactly what a single frame cannot say — and a turn
  // resolves it without anyone having to take hold of the thing. One
  // revolution in 87 seconds, at a rate that does not vary: a speed
  // that wandered was meant to read as less mechanical and read as a
  // wobble instead.
  //
  // The breath goes in far enough to arrive inside the sphere. At the
  // top of it the eye sits a little outside the distance that frames
  // the whole cloud; at the bottom it is at about a fifth of that,
  // which is halfway to the middle — the islands pass to either side
  // and whatever has gone behind the eye is culled. A full breath takes
  // 80 seconds, 40 in and 40 out.
  //
  // It is a factor, not a distance: the breath rides on wherever the
  // wheel was last left, so it means the same thing far out and close
  // in. `home` is what it is a factor of, taken from the eye's own
  // place each time the drift starts, so resuming never jumps.
  const TURN = 0.0012;
  const DIVE = 1.5;
  const RISE = 0.12;
  const WIND = 0.0013;

  let clock = 0;
  let home = away;

  // It is a frame a tick for as long as it runs — under 3 ms of
  // processor on this machine — so it runs only while somebody could be
  // looking at it and is not touching it.
  let resting = false;
  let onScreen = true;
  let pointerOn = false;

  // Where the eye is in the breath, as a factor of `home`.
  function breath() {
    const wave = 0.5 - 0.5 * Math.cos(clock * WIND);
    return Math.exp(RISE - (DIVE + RISE) * wave);
  }

  function settle() {
    const was = resting;
    resting = onScreen && !pointerOn && !stillness.matches;

    // Picking the breath up from where the eye actually is, which is
    // not where it was when the drift last stopped: the wheel may have
    // moved it since, and a factor needs something to be a factor of.
    if (resting && !was) home = away / breath();

    if (resting) keepEasing();
  }

  function drift() {
    clock += 1;
    yaw += TURN;

    away = Math.max(reach * 0.25, Math.min(reach * 12, home * breath()));

    // The place the wheel asked for comes along, so the spring sees no
    // gap and stays out of the breath — and the wheel starts from where
    // the eye is the moment the pointer arrives and the drift stops.
    wantAway = away;
  }

  // The loop runs only while something is moving. A cloud nobody is
  // touching is a still picture and must cost nothing, because every
  // frame here is rasterised by the processor.
  let easing = false;
  let gone = false;

  function keepEasing() {
    if (easing || gone) return;
    easing = true;
    requestAnimationFrame(ease);
  }

  function ease() {
    easing = false;
    if (gone) return;

    let moved = resting;
    if (resting) drift();

    // The spin the pointer handed over, running down. Not while the
    // pointer is still on it: a drag is one to one with the hand, and
    // anything else feels like dragging through water.
    if (!dragging && (Math.abs(turning) > 2e-4 || Math.abs(tipping) > 2e-4)) {
      yaw += turning;

      const tipped = Math.max(-1.45, Math.min(1.45, pitch + tipping));
      // Held at the pole rather than pressing against it for a second.
      if (tipped === pitch) tipping = 0;
      pitch = tipped;

      turning *= GLIDE;
      tipping *= GLIDE;
      moved = true;
    } else if (!dragging) {
      turning = 0;
      tipping = 0;
    }

    const gap = wantAway - away;
    if (Math.abs(gap) > reach * 4e-4 || Math.abs(zooming) > reach * 4e-4) {
      zooming = (zooming + gap * SPRING) * DAMP;
      away += zooming;
      moved = true;
    } else if (away !== wantAway) {
      away = wantAway;
      zooming = 0;
      moved = true;
    }

    if (moved) {
      redraw();
      keepEasing();
    }
  }

  function whereIs(event) {
    const box = canvas.getBoundingClientRect();
    const ratio = canvas.width / box.width;
    return {
      x: (event.clientX - box.left) * ratio,
      y: (event.clientY - box.top) * ratio,
      ratio: ratio,
    };
  }

  function nearest(spot) {
    const lens = (canvas.height / 2) / Math.tan((55 * Math.PI / 180) / 2);
    const middleX = canvas.width / 2;
    const middleY = canvas.height / 2;
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
    // A rebuild under a pointer that never left gets no enter event, so
    // the first movement says so instead.
    if (!pointerOn) {
      pointerOn = true;
      resting = false;
    }

    if (dragging) {
      const spot = whereIs(event);
      const side = (spot.x - dragging.x) * 0.006 / spot.ratio;
      const up = (spot.y - dragging.y) * 0.006 / spot.ratio;

      yaw += side;
      // Stopped short of the poles, where the cloud would flip over.
      pitch = Math.max(-1.45, Math.min(1.45, pitch + up));

      // Kept so the release has something to carry. Most of the last
      // step and a little of the one before, so a drag that slowed to a
      // stop before the fingers came off lets go of nothing.
      turning = turning * 0.3 + side * 0.7;
      tipping = tipping * 0.3 + up * 0.7;

      dragging = spot;
      redraw();
      return;
    }

    const was = over;
    over = nearest(whereIs(event));

    if (over !== was) {
      readout.textContent = over >= 0 ? said.points[over].label : "";
      canvas.style.cursor = over >= 0 ? "pointer" : "grab";
      paint();
    }
  }

  function arrive() {
    pointerOn = true;
    settle();
  }

  // The drift stops under the hand, and the ring and the name go with
  // the pointer when it leaves: a name left in the readout is a claim
  // about where the mouse is that stopped being true.
  function depart() {
    pointerOn = false;
    if (over >= 0) {
      over = -1;
      readout.textContent = "";
      paint();
    }
    settle();
  }

  function grab(event) {
    dragging = whereIs(event);
    began = dragging;
    pointerOn = true;
    resting = false;
    // Catching a cloud still turning stops it, which is what catching
    // something means.
    turning = 0;
    tipping = 0;
    canvas.setPointerCapture(event.pointerId);
  }

  function letGo(event) {
    const spot = whereIs(event);
    const spun = began && (
      Math.abs(spot.x - began.x) > 3 || Math.abs(spot.y - began.y) > 3
    );
    dragging = null;
    began = null;

    if (spun && !stillness.matches) keepEasing();
    settle();

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
    wantAway *= event.deltaY > 0 ? 1.1 : 1 / 1.1;
    // Down to a quarter of the radius, which is inside the cloud: the
    // islands are what this is for, and reading one means getting
    // among it.
    wantAway = Math.max(reach * 0.25, Math.min(reach * 12, wantAway));

    if (stillness.matches) {
      away = wantAway;
      redraw();
      return;
    }

    keepEasing();
  }

  canvas.addEventListener("pointermove", look);
  canvas.addEventListener("pointerdown", grab);
  canvas.addEventListener("pointerup", letGo);
  canvas.addEventListener("pointerenter", arrive);
  canvas.addEventListener("pointerleave", depart);
  canvas.addEventListener("wheel", roll, { passive: false });

  function resize() {
    const wide = frame.clientWidth;
    const tall = frame.clientHeight;
    if (!wide || !tall) return;

    const ratio = Math.min(window.devicePixelRatio, 2);
    canvas.width = Math.round(wide * ratio);
    canvas.height = Math.round(tall * ratio);
    redraw();
  }

  resize();
  settle();

  return {
    resize: resize,

    // The tab the map is on. Off it, nobody is looking and the drift
    // would be a frame a tick spent on a section nobody can see.
    showing: function (on) {
      onScreen = on;
      settle();
    },

    dispose: function () {
      // A frame already asked for would otherwise land on the next
      // selection's canvas and draw the old cloud over it once.
      gone = true;
      canvas.removeEventListener("pointermove", look);
      canvas.removeEventListener("pointerdown", grab);
      canvas.removeEventListener("pointerup", letGo);
      canvas.removeEventListener("pointerenter", arrive);
      canvas.removeEventListener("pointerleave", depart);
      canvas.removeEventListener("wheel", roll);
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
  else if (drawn) drawn.showing(false);
}).observe(document.body, { attributeFilter: ["data-tab"] });

window.addEventListener("resize", function () {
  if (drawn) drawn.resize();
});
