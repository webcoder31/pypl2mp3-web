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

// What the cloud is drawn on. The canvas itself is transparent and so
// is its frame, so the colour comes from whichever ancestor first
// declares one — asking the body instead would give the page's colour
// and not the panel's, and on the light theme those differ.
function behind() {
  let at = canvas.parentElement;

  while (at) {
    const found = getComputedStyle(at).backgroundColor;
    if (found && found !== "transparent" && !found.endsWith(", 0)")) {
      return found;
    }
    at = at.parentElement;
  }

  return getComputedStyle(document.body).backgroundColor || "#fff";
}

// A rectangle with its corners taken off, traced onto a context. Left
// as a path rather than filled, because every mark is this same outline
// filled three or four times over.
function card(ink, x, y, wide, tall, round) {
  const r = Math.min(round, wide / 2, tall / 2);

  ink.beginPath();
  ink.moveTo(x + r, y);
  ink.arcTo(x + wide, y, x + wide, y + tall, r);
  ink.arcTo(x + wide, y + tall, x, y + tall, r);
  ink.arcTo(x, y + tall, x, y, r);
  ink.arcTo(x, y, x + wide, y, r);
  ink.closePath();
}

let drawn = null;
let points = [];
let genres = [];
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
  genres = said.genres;

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
  // hundred gradients a frame; this builds them once for the life of
  // the drawing, and a scaled drawImage is a blit.
  //
  // And one per colour per depth. Distance is said the way a map says
  // it: the far side of the cloud fades towards the colour of the page
  // behind it, the near side keeps its own. That is a mix, not a
  // transparency — the discs stay opaque and nothing shows through
  // anything, which is what made nine hundred translucent ones a haze
  // the first time.
  //
  // Eight steps rather than a value per point, because a value per
  // point is a gradient per point per frame. At this size the steps do
  // not read as bands: the points are small, scattered, and no two
  // neighbours in the picture are neighbours in depth.
  const STEPS = 8;
  const HAZE = 0.5;

  // The mark: a card, in the proportion a bank card has — 85.60 by
  // 53.98 millimetres, so a shade over 1.58 — with its corners just
  // off square. A ninth of its height, which at the largest a song is
  // ever drawn comes to two pixels: enough to soften a corner, not
  // enough to make a lozenge of it.
  const CARD = 1.586;
  const ROUND = 0.11;

  // A card of the same area as the square it replaces, so swapping the
  // shape did not quietly change how heavy the cloud is.
  const WIDER = Math.sqrt(CARD);

  const SPRITE_H = 44;
  const SPRITE_W = Math.round(SPRITE_H * CARD);

  // How much of the box the size is measured in the mark fills. Full
  // width it would be a third heavier than the disc it replaces — 4r²
  // against πr² — and the cloud would thicken for no reason anyone
  // asked for.
  const FILL = 0.8;

  // The slope of light across each card, from its top-left corner to
  // its bottom-right.
  //
  // Two marks of one colour that overlap read as one odd shape, and
  // nothing says which is in front. A rule between them was tried
  // twice: in the page's colour it cut a white gash through every
  // crowd, and in a darker shade of the mark it drew a border round
  // things that are not bordered anywhere else on this page.
  //
  // A slope needs nothing drawn at all. Where a near card lands on a
  // far one its lit corner meets the other's shaded end, and the join
  // shows by itself. It is slight on purpose — a seventh of a tone up
  // and a sixth down — so that a card alone still reads as one flat
  // colour, which is what the legend promises.
  const SLOPE_UP = 0.14;
  const SLOPE_DOWN = 0.17;

  // How deep the frame's edge is feathered, as a share of its shorter
  // side.
  //
  // A cloud that is turning and breathing keeps pushing songs past the
  // edge of the frame, and a card that meets it is simply cut in half:
  // a straight line through a thing that has no straight lines in it.
  // Faded out over the last stretch instead, a card leaves the picture
  // rather than being severed by it.
  //
  // Laid over the whole cloud once, not worked out card by card: it is
  // the same colour as the page, so on open ground it does nothing and
  // nothing has to be made translucent to get it.
  const FEATHER = 0.14;

  // The pool of accent the cloud sits in, and how strong it is at its
  // middle.
  //
  // The page has exactly one colour of its own and uses it for the
  // thing in hand — the playing row, the transport, the accent line.
  // A soft green under the middle of the cloud says the map belongs to
  // the same page, and gives the eye a centre to read the turning
  // against: a cloud on bare white has no horizon.
  //
  // It sits under the cards and not over them, so it can never dull a
  // colour the legend promises. On white, 0.17 of the accent reads as
  // rgb(213, 236, 233); on the dark theme, rgb(23, 49, 47).
  //
  // The falloff matters as much as the strength: half the light still
  // standing at half the radius makes a pool, where the first version
  // kept a third and made a point of light with nothing around it.
  // How much colour the middle carries, and how much is left half way
  // out. Two numbers rather than one and a fraction of it, so the
  // middle can be made brighter without the rest of the pool coming up
  // with it: 0.09 half way out is what 0.17 and a 0.55 fraction gave
  // before, so only the core has moved.
  //
  // And the middle's saturation is lifted a quarter, capped at full.
  // On the light theme the accent is already at 87 and barely moves;
  // on the dark one it sits at 55, where raising the alpha alone would
  // have made the middle paler rather than more vivid.
  const POOL_IS = 0.23;
  const POOL_MID = 0.09;
  const POOL_LIFT = 1.25;

  // Its reach is not a number of its own: it is the cloud's own size on
  // screen. The cloud is a ball of radius `reach`, so at a distance of
  // `away` it projects to `reach * lens / away` — the pool is that,
  // and grows and shrinks with the thing it sits behind rather than
  // with a ramp somebody chose. Two earlier versions set it by hand
  // and neither could follow a cloud that breathes.
  //
  // Checked against the cloud it is meant to follow, by measuring the
  // furthest card actually drawn: within a tenth of it from twelve
  // radii down to about two, and exact at 2.6. Nearer than that the
  // real cloud bursts the frame — a card beside the eye projects
  // thousands of pixels out — while the formula keeps describing the
  // ball, which is the useful thing to be behind. By then the pool is
  // on its way out anyway: full at 1.0, which is the surface, and
  // three quarters of the way down by 0.47.
  //
  // Clamped at both ends: coming inside, `away` goes small and the
  // projection runs away, and there is no cloud left to be behind.
  const POOL_LEAST = 0.1;
  const POOL_MOST = 1.2;

  // And it fades as the eye comes in, between these two distances in
  // radii.
  //
  // Neither is a number anyone picked. The pool is full down to 1.0,
  // which is the cloud's own surface — the fade begins exactly where
  // the eye goes inside — and is spent by 0.3, just short of the
  // 0.25 the wheel stops at. A pool marks the middle of a thing you
  // are looking at; once you are well inside, the cards pass to either
  // side and there is no middle left to mark.
  //
  // It started at 0.8 and 1.6, which began dimming while the eye was
  // still well outside and left the pool wholly dark for 38% of the
  // breath. At 0.3 and 1.0 it is at full strength for 53% of the cycle
  // and never goes out: at the deepest of the dive it still stands at
  // a quarter.
  const POOL_GONE = 0.3;
  const POOL_FULL = 1.0;


  let blocks = new Map();
  let inks = new Map();
  let paper_colour = behind();

  // Any CSS colour as three numbers. Painting it and reading the pixel
  // back is the only way to do this that is not a parser for every
  // notation the page might reasonably use.
  function rgbOf(colour) {
    const nib = document.createElement("canvas").getContext(
      "2d", { willReadFrequently: true }
    );
    nib.fillStyle = colour;
    nib.fillRect(0, 0, 1, 1);

    const got = nib.getImageData(0, 0, 1, 1).data;
    return [got[0], got[1], got[2]];
  }

  // The same colour as hue, saturation and lightness. Hue is the one
  // of the three the pool moves, and moving it in RGB means moving all
  // three together and hoping — this is the space the question is
  // asked in.
  function hslOf(colour) {
    const [r, g, b] = rgbOf(colour).map(function (v) { return v / 255; });

    const high = Math.max(r, g, b);
    const low = Math.min(r, g, b);
    const light = (high + low) / 2;
    const span = high - low;

    if (span === 0) return { hue: 0, sat: 0, light: light * 100 };

    const sat = span / (1 - Math.abs(2 * light - 1));
    let hue;

    if (high === r) hue = ((g - b) / span) % 6;
    else if (high === g) hue = (b - r) / span + 2;
    else hue = (r - g) / span + 4;

    return {
      hue: (hue * 60 + 360) % 360,
      sat: sat * 100,
      light: light * 100,
    };
  }

  // Which way to push, decided by the page rather than by a flag: the
  // theme is a fact about the colour behind the letters.
  function inkFor(tint) {
    const page = rgbOf(paper_colour);
    const bright =
      0.2126 * page[0] + 0.7152 * page[1] + 0.0722 * page[2] > 128;

    const push = bright
      ? function (v) { return Math.round(v * DARKEN); }
      : function (v) { return Math.round(v + (255 - v) * LIGHTEN); };

    return "rgb(" + rgbOf(tint).map(push).join(", ") + ")";
  }
  let veil = null;
  let veilDeep = 0;
  let pool = null;

  // The name of the song, set on the canvas in the font the page uses
  // for its own small print. Read when the frame is measured or the
  // theme changes, rather than every frame.
  let lettering = "12px sans-serif";
  let grain = 1;

  // A name is written in its card's own colour, pushed away from the
  // page far enough to be read: darkened on the light theme, lightened
  // on the dark one.
  //
  // Measured across the thirteen colours, worst case, against the page
  // behind them. Untouched they come to 1.75 to one on white, which is
  // no contrast at all. Darkened to 55% they reach 5.28; lightened by
  // a quarter on the dark theme, 6.26. Both clear the 4.5 that small
  // text is held to, and the hue survives — a darkened teal is still
  // teal, which is the whole reason for taking the card's colour.
  const DARKEN = 0.55;
  const LIGHTEN = 0.25;

  // While the cloud is turning on its own, it names a few of the songs
  // nearest the eye, in turn.
  //
  // A map nobody is touching is otherwise nine hundred anonymous marks,
  // and the one thing a reader wants to know of it — what is this? —
  // needs a hand on the mouse to ask. Three at a time is the most that
  // can be read before they change; more is a crowd, and one is a
  // slideshow.
  //
  // One name a second, each staying three, so three are up at any
  // moment and each is a second older than the last. A set of three
  // arriving and leaving together reads as a slideshow; staggered, the
  // map is simply naming things as it turns.
  //
  // DAWN is how long one takes to arrive and to leave, which is why the
  // one going and the one coming overlap instead of blinking. In
  // frames, off the same clock the drift runs on, so they stop when it
  // stops rather than sitting on a still picture.
  //
  // Not RISE, which this drawing already uses for how far the breath
  // reaches outward.
  const EVERY = 60;
  const LIFE = 180;
  const DAWN = 24;
  const NAMES = 3;

  // How wide a card must be drawn, in CSS pixels, before it is worth
  // naming.
  //
  // Not a zoom level, though that is what it amounts to: the cause is
  // the size of the thing the name is pointing at. Measured through
  // the module, the widest card in the cloud comes to 1.2 pixels at
  // the far end of the wheel, 3.0 at four radii, 7.5 at the distance
  // the map opens on, and 36 from inside. Under about five it is a
  // speck, and a name floating over a field of specks belongs to none
  // of them.
  //
  // Eight. Sampled over a whole breath at the framing the map opens
  // on, the widest card runs between 5.7 and 36.3 pixels — the breath
  // dives right inside the cloud, so it is never truly small — and a
  // threshold of eight leaves names being chosen 77% of that cycle
  // against 100% at five. The map therefore goes quiet at the far end
  // of each breath and speaks again coming in, which is also when
  // there is something to point at.
  //
  // It gates the choosing only: a name already up lives out its three
  // seconds rather than blinking off the moment the wheel turns.
  const NAMEABLE = 8;

  // The gap between a card's ring and the first letter of its name, in
  // CSS pixels.
  const BESIDE = 5;

  // Two names on one line overlap; two on different lines do not. Both
  // have to be close for a candidate to be refused, and how close is
  // `longest` — a name may be exactly as wide as the gap two names are
  // required to keep, and no wider. A limit and a spacing that did not
  // agree would let two "separated" names overlap anyway.
  const APART_Y = 28;

  // The longest a name may be drawn, in the canvas's own pixels.
  //
  // Measured on the library, in the face this draws in: the median name
  // is 188 pixels wide, three quarters are under 263, and the longest —
  // "Franco Micalizzi & Gianfranco Plenzio - Trinity: titoli (feat.
  // Annibale & I Cantori Moderni di Alessandroni) [Remastered 2022]" —
  // runs to 698, two thirds of the frame. Centred on its card it
  // reached clean across the cloud.
  //
  // A quarter of the frame rather than a number, so it follows the
  // window instead of being right at one size only. At the width this
  // was written for that is 250 pixels, which shortens about three
  // names in ten and leaves three of them filling three quarters of
  // the frame at worst.
  let longest = 250;

  // How long before a song may be named again, in frames. A minute.
  //
  // The walk always starts from the front of the cloud, and the front
  // of a cloud turning this slowly is much the same from one second to
  // the next — so the same few songs were named over and over. With a
  // memory, a song that has just been named is passed over and the
  // walk goes a little deeper to find the next, which is both more
  // varied and more honest about how much is out there.
  const AGAIN = 3600;

  let spoke = -1;
  let named = [];
  const told = new Map();

  // Any CSS colour as three numbers. Painting it and reading the pixel
  // back is the only way to do this that is not a parser for every
  // notation the page might reasonably use.
  function rgbOf(colour) {
    const nib = document.createElement("canvas").getContext(
      "2d", { willReadFrequently: true }
    );
    nib.fillStyle = colour;
    nib.fillRect(0, 0, 1, 1);

    const got = nib.getImageData(0, 0, 1, 1).data;
    return [got[0], got[1], got[2]];
  }

  // Four bands, one a side, each going from the page's colour at the
  // frame to nothing a little way in. Built when the frame changes
  // size or the theme changes, and not every frame.
  function weave() {
    const wide = canvas.width;
    const tall = canvas.height;
    if (!wide || !tall) return;

    const [r, g, b] = rgbOf(paper_colour);
    const solid = "rgba(" + r + ", " + g + ", " + b + ", 1)";
    const clear = "rgba(" + r + ", " + g + ", " + b + ", 0)";

    veilDeep = Math.min(wide, tall) * FEATHER;
    longest = Math.max(120 * grain, wide / 4);

    // The cut depends on the width, so nothing keeps its old one.
    named.forEach(function (one) { one.text = null; });

    const small = getComputedStyle(note);
    lettering = Math.round(parseFloat(small.fontSize) * grain)
      + "px " + small.fontFamily;

    const band = function (x1, y1, x2, y2) {
      const run = paper.createLinearGradient(x1, y1, x2, y2);
      run.addColorStop(0, solid);
      run.addColorStop(1, clear);
      return run;
    };

    // The accent, read from the stylesheet like everything else, so it
    // turns with the theme.
    // Kept as hue, saturation and lightness rather than as three
    // numbers, because the hue is the part that moves: the pool keeps
    // the page's accent for its depth and its paleness, and borrows
    // only its angle on the wheel from the clock.
    pool = hslOf(
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent").trim() || "#0a8f7c"
    );

    veil = {
      top: band(0, 0, 0, veilDeep),
      bottom: band(0, tall, 0, tall - veilDeep),
      left: band(0, 0, veilDeep, 0),
      right: band(wide, 0, wide - veilDeep, 0),
      wide: wide,
      tall: tall,
    };
  }

  // How far gone a point at this spot already is, nought to one: the
  // pointer should not find a song the veil has taken.
  function veiled(px, py) {
    if (!veil || veilDeep <= 0) return 0;

    return Math.max(
      0,
      1 - px / veilDeep,
      1 - (veil.wide - px) / veilDeep,
      1 - py / veilDeep,
      1 - (veil.tall - py) / veilDeep
    );
  }

  // A card, facing the reader, in one flat colour.
  //
  // It has been a shaded sphere and a shaded cube on the way here, and
  // both were wrong for the same reason: the page they sit on is flat.
  // Hairlines, type, one accent, no relief anywhere — and then nine
  // hundred lit solids. The sphere read as a balloon and the cube,
  // though it belonged to the right family of shapes, still modelled a
  // volume the rest of the interface does not have.
  //
  // The map already carries all the depth it needs, and carries it the
  // way a map does: things further off are smaller, and paler. Nothing
  // has to be modelled on top of that.
  //
  // What the cube cost is worth keeping in mind if anyone brings it
  // back. Every cube shares one silhouette, since they are all turned
  // the same way, so it was still one sprite stamped — but the
  // silhouette had to be re-cut whenever the view turned, and doing
  // all thirteen colours in one frame cost 12.6ms against a median of
  // 2.6. A card never turns, so it is cut once and kept.
  function block(tint, fade) {
    const pad = document.createElement("canvas");
    pad.width = SPRITE_W;
    pad.height = SPRITE_H;

    const ink = pad.getContext("2d");

    // Half a pixel in, so the rounded corners have somewhere to soften.
    const trace = function () {
      card(ink, 0.5, 0.5, SPRITE_W - 1, SPRITE_H - 1, SPRITE_H * ROUND);
    };

    trace();
    ink.fillStyle = tint;
    ink.fill();

    // Two passes rather than one gradient from white to black: a single
    // one interpolates through a grey with alpha in the middle, which
    // would put a smudge across the centre of every card.
    const lit = ink.createLinearGradient(0, 0, SPRITE_W, SPRITE_H);
    lit.addColorStop(0, "rgba(255, 255, 255, " + SLOPE_UP + ")");
    lit.addColorStop(0.55, "rgba(255, 255, 255, 0)");
    trace();
    ink.fillStyle = lit;
    ink.fill();

    const dim = ink.createLinearGradient(0, 0, SPRITE_W, SPRITE_H);
    dim.addColorStop(0.45, "rgba(0, 0, 0, 0)");
    dim.addColorStop(1, "rgba(0, 0, 0, " + SLOPE_DOWN + ")");
    trace();
    ink.fillStyle = dim;
    ink.fill();

    if (fade > 0) {
      trace();
      ink.globalAlpha = fade;
      ink.fillStyle = paper_colour;
      ink.fill();
    }

    return pad;
  }

  // Every colour at every depth. Thirteen colours and eight steps is a
  // hundred and four little canvases, built once and kept for the life
  // of the drawing.
  function blocksFor(tint) {
    const set = [];
    for (let step = 0; step < STEPS; step++) {
      set.push(block(tint, (step / (STEPS - 1)) * HAZE));
    }

    return set;
  }

  // The cloud's own centre, so the eye turns about the middle of it
  // and not about wherever the relaxation happened to leave the origin.
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

  let yaw = 0.4;
  let pitch = 0.2;

  let reach = 1;
  const cloud = said.points.map(function (one, at) {
    const x = one.at[0] - middle[0];
    const y = one.at[1] - middle[1];
    const z = one.at[2] - middle[2];

    reach = Math.max(reach, Math.sqrt(x * x + y * y + z * z));

    const tint = one.shade >= 0 ? colours.lit[one.shade] : colours.dim;
    if (!blocks.has(tint)) {
      blocks.set(tint, blocksFor(tint));
      inks.set(tint, inkFor(tint));
    }

    return {
      at: at,
      x: x, y: y, z: z,
      tint: tint,
      tintAt: one.shade,
    };
  });

  // How far the eye stands off: far enough that the whole cloud fits
  // the frame.
  //
  // A sphere of radius `reach` fills a 55-degree frame from
  // reach / sin(27.5°) = 2.17 away; a little further leaves a margin.
  // At 3.2, which is what the first camera here used, the cloud sat in
  // the middle third of the frame and the rest was empty.
  // The breath, as the three distances that define it, in cloud radii.
  //
  // Read off the wheel's own scale, which is logarithmic because the
  // wheel multiplies the distance by 1.1 a notch rather than adding to
  // it: 0% is its far stop at 12 radii and 100% its near one at 0.25,
  // and the whole range is forty-one notches. On that scale the breath
  // runs from 30% to 65% and the map opens at 45%.
  //
  // So it opens part-way in and breathes both outward and inward from
  // there, rather than opening at one of its own extremes as it did
  // before. Where exactly it opens in the cycle is arithmetic rather
  // than a choice: away(w) is BREATH_OUT * exp(-S*w), so the phase is
  // ln(OUT/OPENS) / S — here a shade under halfway into the dive.
  const BREATH_OUT = 3.757;
  const BREATH_IN = 0.969;
  const OPENS_AT = 2.102;

  let away = reach * OPENS_AT;

  // How big a song is, as a fraction of the cloud's own radius. Opaque
  // and small: nine hundred translucent discs over each other made a
  // haze where the eye wanted points, and the colours mixed into
  // something that was nobody's genre.
  const POINT = 0.011;
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
    const wide = canvas.width;
    const tall = canvas.height;
    if (!wide || !tall) return;

    // 55 degrees: wide enough to hold the cloud, narrow enough that
    // the perspective still says which islands are in front.
    const lens = (tall / 2) / Math.tan((55 * Math.PI / 180) / 2);
    const middleX = wide / 2;
    const middleY = tall / 2;
    paper.clearRect(0, 0, wide, tall);

    // Under everything: the cloud sits in it, nothing sits in front of
    // a card because of it.
    const pooling = Math.max(0, Math.min(
      1, (away / reach - POOL_GONE) / (POOL_FULL - POOL_GONE)
    ));

    if (pool && pooling > 0.01) {
      // The cloud's own silhouette, projected: the pool is as big as
      // the thing it sits behind.
      const span = Math.min(wide, tall);
      const spread = Math.max(
        span * POOL_LEAST,
        Math.min(span * POOL_MOST, reach * lens / Math.max(away, 1e-6))
      );

      const wash = paper.createRadialGradient(
        wide / 2, tall / 2, 0,
        wide / 2, tall / 2, spread
      );
      // Round the wheel from wherever the accent sits.
      const hue = (pool.hue + 360 * (clock / HUE_TURN)) % 360;
      const poured = function (alpha, sat) {
        return "hsla(" + hue.toFixed(1) + ", " + sat.toFixed(1)
          + "%, " + pool.light.toFixed(1) + "%, " + alpha + ")";
      };

      const core = Math.min(100, pool.sat * POOL_LIFT);

      wash.addColorStop(0, poured(POOL_IS, core));
      wash.addColorStop(0.5, poured(POOL_MID, pool.sat));
      wash.addColorStop(1, poured(0, pool.sat));

      paper.globalAlpha = pooling;
      paper.fillStyle = wash;
      paper.fillRect(0, 0, wide, tall);
      paper.globalAlpha = 1;
    }

    // Where the name goes, once everything else is down: drawn inside
    // the loop it would be covered by whichever cards come after.
    let naming = null;

    // Far to near, so the near ones cover what is behind them — which
    // is the whole of what a depth buffer was doing.
    const order = flat.slice().sort(function (a, b) {
      return b.depth - a.depth;
    });

    // The near and far walls of the cloud as the eye stands now, so the
    // haze is read off the cloud and not off an absolute distance: the
    // breath moves the eye by a factor of five and a fixed scale would
    // wash the whole thing out at the far end of it.
    const nearest = Math.max(0.1, away - reach);
    const depth = Math.max(0.0001, (away + reach) - nearest);

    // Whose names are up, while nobody is pointing. `order` runs far to
    // near, so the nearest are at its end and the walk is backwards —
    // it reads a handful and stops, not nine hundred.
    // Cleared when the drift is spent, not when the pointer arrives:
    // the names fade out with everything else rather than blinking
    // off. New ones are only chosen while the drift is wanted.
    if (drifting <= 0) {
      spoke = -1;
      named = [];
    } else if (resting) {
      named = named.filter(function (one) {
        return clock - one.born < LIFE;
      });

      const turn = Math.floor(clock / EVERY);
      if (turn !== spoke) {
        spoke = turn;

        for (let i = order.length - 1; i >= 0 && named.length < NAMES; i--) {
          const seen = order[i];
          if (seen.depth <= 0.1) continue;

          const when = told.get(seen.at);
          if (when !== undefined && clock - when < AGAIN) continue;

          const scale = lens / seen.depth;
          const big = Math.min(
            18, Math.max(0.6, reach * POINT * lens / seen.depth)
          );
          if (2 * big * FILL * WIDER < NAMEABLE * grain) continue;

          const px = middleX + seen.x * scale;
          const py = middleY - seen.y * scale;
          if (veiled(px, py) > 0.4) continue;

          // Against where the others are now, not where they were when
          // they were chosen: the cloud has turned since.
          const clear = named.every(function (other) {
            return Math.abs(other.x - px) > longest
              || Math.abs(other.y - py) > APART_Y * grain;
          });
          if (!clear) continue;

          named.push({ at: seen.at, x: px, y: py, born: clock });
          told.set(seen.at, clock);
          break;
        }
      }
    }

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

      const far = (seen.depth - nearest) / depth;
      const step = Math.max(0, Math.min(
        STEPS - 1, Math.floor(far * STEPS)
      ));

      const wide = size * FILL * WIDER;
      const tall = size * FILL / WIDER;

      paper.drawImage(
        blocks.get(seen.tint)[step], x - wide, y - tall, wide * 2, tall * 2
      );

      if (seen.at === over) {
        // The same outline, stood off a few pixels: a circle would say
        // the pointer had found something round.
        const out = 3.5;

        card(
          paper, x - wide - out, y - tall - out,
          (wide + out) * 2, (tall + out) * 2, (tall + out) * 2 * ROUND
        );
        paper.lineWidth = 1.5;
        paper.strokeStyle = seen.tint;
        paper.stroke();

        naming = {
          x: x + wide + out + BESIDE * grain,
          y: y,
          ink: inks.get(seen.tint),
        };
      }
    }

    if (veil) {
      paper.fillStyle = veil.top;
      paper.fillRect(0, 0, wide, veilDeep);
      paper.fillStyle = veil.bottom;
      paper.fillRect(0, tall - veilDeep, wide, veilDeep);
      paper.fillStyle = veil.left;
      paper.fillRect(0, 0, veilDeep, tall);
      paper.fillStyle = veil.right;
      paper.fillRect(wide - veilDeep, 0, veilDeep, tall);
    }

    // Over the veil rather than under it: a name is the interface
    // answering a question, not part of the cloud, and a half-faded
    // answer is no answer.
    paper.font = lettering;
    // Beside the card rather than over it, and level with its middle:
    // the name reads as a caption attached to the thing, the way a
    // place name sits beside its dot on a map.
    paper.textAlign = "left";
    paper.textBaseline = "middle";
    paper.lineJoin = "round";

    // Laid over a crowd of cards, a line of text is unreadable on its
    // own. The page's colour behind it, drawn as a fat stroke under the
    // letters, is what a map does with a place name over a forest.
    // As much of a name as fits, and an ellipsis for the rest. Cut at
    // a space when one is near the end, so the break lands between
    // words rather than in the middle of one.
    function fits(name) {
      if (paper.measureText(name).width <= longest) return name;

      let lo = 0;
      let hi = name.length;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (paper.measureText(name.slice(0, mid) + "…").width <= longest) {
          lo = mid;
        } else {
          hi = mid - 1;
        }
      }

      let cut = name.slice(0, lo);
      const space = cut.lastIndexOf(" ");
      if (space > 0 && space > lo - 12) cut = cut.slice(0, space);

      return cut.replace(/[ \-–—:,]+$/, "") + "…";
    }

    function say(name, atX, atY, alpha, ink) {
      // Set here and not once above, because the ring a named card
      // wears borrows the same property between two calls of this.
      paper.lineWidth = 4 * grain;

      // Centred on its card, and left there. Holding it inside the
      // frame was tried: it keeps every name whole, but it slides the
      // name off the card it belongs to, and a name that points at the
      // wrong card is worse than one the edge has taken. A name that
      // reaches the border is cut, and fades under the veil on its way
      // out, which is what the border is for.
      paper.globalAlpha = alpha;
      paper.strokeStyle = paper_colour;
      paper.strokeText(name, atX, atY);
      paper.fillStyle = ink;
      paper.fillText(name, atX, atY);
      paper.globalAlpha = 1;
    }

    if (naming) {
      say(fits(said.points[over].label), naming.x, naming.y, 1, naming.ink);
    } else {
      named.forEach(function (one) {
        const seen = flat[one.at];
        if (seen.depth <= 0.1) return;

        // Re-read each frame: the cloud turns while the name is up, and
        // a name that stayed where the card was is a label for nothing.
        // Kept on the entry too, so the next one chosen is placed
        // against where this one has got to.
        const scale = lens / seen.depth;
        const big = Math.min(
          18, Math.max(0.6, reach * POINT * lens / seen.depth)
        );
        one.x = middleX + seen.x * scale;
        one.y = middleY - seen.y * scale;

        // Cut once and kept: the width does not change between frames,
        // and weave() clears these when it does.
        if (!one.text) one.text = fits(said.points[one.at].label);

        // In and out rather than on and off, each on its own age.
        const age = clock - one.born;
        const alpha = drifting * Math.min(
          1, age / DAWN, Math.max(0, (LIFE - age) / DAWN)
        );

        // Ringed while it is named, in its own colour and fading with
        // the name: at this size a card is a few pixels, and a name
        // hanging over a field of them says nothing about which. The
        // same mark the pointer makes, because it means the same
        // thing — this one.
        const wide = big * FILL * WIDER;
        const tall = big * FILL / WIDER;
        const out = 3.5;

        paper.globalAlpha = alpha;
        card(
          paper, one.x - wide - out, one.y - tall - out,
          (wide + out) * 2, (tall + out) * 2, (tall + out) * 2 * ROUND
        );
        paper.lineWidth = 1.5;
        paper.strokeStyle = seen.tint;
        paper.stroke();
        paper.globalAlpha = 1;

        say(
          one.text,
          one.x + wide + out + BESIDE * grain,
          one.y,
          alpha,
          inks.get(seen.tint)
        );
      });
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
  // revolution in 44 seconds, at a rate that does not vary: a speed
  // that wandered was meant to read as less mechanical and read as a
  // wobble instead.
  //
  // The axis it turns on drifts as well, at its own constant rate. A
  // spin alone shows the cloud from one latitude for ever, so the same
  // islands stay in front of the same islands; tipping the axis across
  // a radian either way brings the rest round in turn.
  //
  // It turns back at the ends rather than running on. Past a quarter
  // turn the cloud is upside down and a drag upwards sends it down,
  // which is why the pointer is stopped at 1.45 — a drift that ran on
  // would either stop dead against that or hand over an inverted
  // cloud. Reversing is the only discontinuity in the whole movement:
  // two moments in a sweep of fourteen thousand frames.
  //
  // The breath goes in far enough to arrive inside the sphere. At the
  // top of it the eye sits a little outside the distance that frames
  // the whole cloud; at the bottom it is at about a fifth of that,
  // which is halfway to the middle — the islands pass to either side
  // and whatever has gone behind the eye is culled. A full breath takes
  // 62 seconds, 31 in and 31 out.
  //
  // It is a factor, not a distance, and `home` is what it is a factor
  // of. Taken from the eye's own place each time the drift starts, so
  // resuming never jumps — and then drawn back, over a few seconds,
  // to the distance that frames the whole cloud.
  //
  // Riding for ever on wherever the wheel was left was the first
  // version and it was wrong: zoom in once, leave, and the breath
  // stayed shrunk around that spot. The far end of it never came back
  // out far enough to show the cloud again. A wheel is a look at
  // something, not a new home.
  //
  // HOMING is what is left of the distance from home each frame: at
  // 0.006 the eye is most of the way back in three seconds and all the
  // way in about a dozen, which is slow enough that nobody sees it
  // being pulled.
  const HOMING = 0.006;
  const TURN = 0.0024;
  const TIP = 0.00028;
  const SWING = 1.0;
  // The swing, derived from the two ends rather than set: their ratio
  // is the whole of it, and RISE is only how much of that sits outward
  // of the anchor.
  const RISE = 0.12;
  const DIVE = Math.log(BREATH_OUT / BREATH_IN) - RISE;
  const WIND = 0.0017;

  // How long the pool's colour takes to go round the wheel, in frames.
  // Down here and not with the pool's other constants, because it is
  // read off WIND and a `const` used above its declaration is a dead
  // zone — the drawing threw before it drew anything, and no test could
  // see it: they read this file, they do not run it.
  //
  // Deliberately out of step with the breath. The golden section is the
  // ratio that comes back into step least often of any, so a colour and
  // a point in the breath keep meeting in a combination they have not
  // been in before — which is the whole reason for turning the colour
  // at all. A whole number of breaths would have paired the same green
  // with the same depth every minute for ever.
  //
  // A sixth of it, so the wheel turns in 17 seconds against the
  // breath's 62. Dividing costs nothing: a rational fraction of an
  // irrational number is irrational, so the two still never come back
  // into step. Six and not a power of two because the two are tied —
  // the colour's period is read off the breath's, so speeding the
  // breath speeds the colour too, and six is what leaves the colour at
  // half of what it was.
  //
  // Saturation and lightness stay the accent's. Only the angle moves,
  // so every colour it passes through is the page's own colour in
  // another key rather than a hue out of nowhere.
  const HUE_TURN = (2 * Math.PI / WIND) * (1.618 / 6);

  // Where in the cycle the map opens. The wave is 0.5 - 0.5cos, which
  // puts the far end at phase nought, so opening part-way in means
  // starting part-way round.
  const OPENS_WAVE = Math.log(BREATH_OUT / OPENS_AT) / (DIVE + RISE);

  let clock = Math.acos(1 - 2 * OPENS_WAVE) / WIND;
  // Where the breath belongs: the top of it is the distance that frames
  // the whole cloud, which is where the eye starts.
  const settled = reach * BREATH_OUT / Math.exp(RISE);
  let home = settled;
  let tilting = 1;

  // It is a frame a tick for as long as it runs — under 3 ms of
  // processor on this machine — so it runs only while somebody could be
  // looking at it and is not touching it.
  let resting = false;
  let onScreen = true;
  let pointerOn = false;

  // How much of the drift is running, nought to one.
  //
  // The pointer arriving used to stop it dead. A cloud that freezes
  // mid-turn reads as a fault rather than as deference — the thing was
  // moving, a hand came near, and it broke. It winds down instead, and
  // winds back up when the hand leaves.
  //
  // Everything the drift does is scaled by this, the clock included —
  // so the turn, the tilt, the breath and the colour all slow together
  // rather than one of them stopping first. EASE is what is left of
  // the distance to the target each frame: at 0.06 it is half gone in
  // a fifth of a second and spent in a second and a half.
  const EASE = 0.06;
  let drifting = 0;

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

    if (resting || drifting > 0) {
      keepEasing();
    } else if (was) {
      // Nothing is going to ask for another frame now, and the last one
      // drawn still carries the names the drift had put up. They would
      // sit there, frozen, for as long as the pointer stayed on the
      // map.
      paint();
    }
  }

  function drift() {
    clock += drifting;
    yaw += TURN * drifting;

    home += (settled - home) * HOMING * drifting;

    // Reversed rather than clamped: a drag can leave the tilt outside
    // this range, and clamping would snap it back the moment the
    // pointer left. Turning it round instead costs one frame's worth
    // of travel and brings it home on its own.
    pitch += TIP * tilting * drifting;
    if (tilting > 0 ? pitch >= SWING : pitch <= -SWING) tilting = -tilting;

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

    // Towards one while the drift is wanted and towards nought while
    // it is not, and the drift runs for as long as anything is left of
    // it — which is what makes the stop a slowing rather than a cut.
    const asked = resting ? 1 : 0;
    let moved = false;

    if (Math.abs(drifting - asked) > 0.004) {
      drifting += (asked - drifting) * EASE;
      moved = true;
    } else if (drifting !== asked) {
      drifting = asked;
      moved = true;
    }

    if (drifting > 0) {
      drift();
      moved = true;
    }

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
      const px = middleX + seen.x * scale;
      const py = middleY - seen.y * scale;
      if (veiled(px, py) > 0.75) continue;

      const dx = px - spot.x;
      const dy = py - spot.y;
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
      settle();
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

  // The sprites carry the page's colour inside them, so a theme change
  // has to rebuild them: otherwise the far side of the cloud goes on
  // fading towards a white that is no longer there.
  function retint() {
    paper_colour = behind();
    weave();

    const colours = palette();
    blocks = new Map();
    inks = new Map();
    cloud.forEach(function (one) {
      one.tint = one.tintAt >= 0 ? colours.lit[one.tintAt] : colours.dim;
      if (!blocks.has(one.tint)) {
        blocks.set(one.tint, blocksFor(one.tint));
        inks.set(one.tint, inkFor(one.tint));
      }
    });

    redraw();
  }

  function resize() {
    const wide = frame.clientWidth;
    const tall = frame.clientHeight;
    if (!wide || !tall) return;

    const ratio = Math.min(window.devicePixelRatio, 2);
    grain = ratio;
    canvas.width = Math.round(wide * ratio);
    canvas.height = Math.round(tall * ratio);
    weave();
    redraw();
  }

  resize();
  settle();

  return {
    resize: resize,
    retint: retint,

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

new MutationObserver(function () {
  if (drawn) {
    drawn.retint();
    showLegend(genres);
  }
}).observe(document.documentElement, { attributeFilter: ["data-theme"] });
