// The console's persistent player and selection.
//
// The queue is built from the rows in #list at the moment you start
// playing, and then it is its own thing. It has to be: filtering while
// the music plays is the point of this layout, and the row you are
// hearing may well not be on screen any more.
//
// That is why each entry carries its label rather than looking one up in
// the DOM. A lookup that missed used to fall back to the YouTube id, so
// filtering mid-track turned the player's title into `iwMP-vXX7Pk`.
//
// Playback state lives here and only here. #player sits outside every
// htmx target, so swapping the list, the nav or the inspector leaves the
// <audio> element — and the sound — untouched.

(function () {
  "use strict";

  // ---------------------------------------------------------------
  // Theme
  //
  // Three settings: follow the system, light, dark. The middle of those
  // is why the palette is an attribute rather than a media query — a
  // query cannot express "unless the reader said otherwise".
  //
  // The <head> resolved and applied the stored choice before the first
  // paint. This keeps the buttons in step, remembers a new choice, and
  // follows the system while the choice is to follow it.
  // ---------------------------------------------------------------

  const THEME_KEY = "pypl2mp3.theme";
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");

  function applyTheme(choice) {
    const wanted = ["auto", "light", "dark"].includes(choice)
      ? choice
      : "auto";
    const dark = wanted === "dark" || (wanted === "auto" && prefersDark.matches);

    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.themeChoice = wanted;

    document.querySelectorAll("#theme button[data-theme-choice]").forEach(
      function (button) {
        button.setAttribute(
          "aria-pressed", String(button.dataset.themeChoice === wanted)
        );
      }
    );

    return wanted;
  }

  applyTheme(document.documentElement.dataset.themeChoice);

  // Only while the choice is to follow: an explicit light or dark must
  // survive the system changing under it.
  prefersDark.addEventListener("change", function () {
    if (document.documentElement.dataset.themeChoice === "auto") {
      applyTheme("auto");
    }
  });

  document.addEventListener("click", function (event) {
    const pick = event.target.closest("#theme button[data-theme-choice]");
    if (!pick) return;

    try {
      localStorage.setItem(THEME_KEY, applyTheme(pick.dataset.themeChoice));
    } catch (error) {
      // Private browsing refuses localStorage. The switch still works
      // for this page; it just will not be remembered.
    }
  });

  // ---------------------------------------------------------------
  // Tabs
  //
  // The playlist and the imports are two views of one column. Both panes
  // are already in the document, so switching is a class on the body: a
  // round trip to change which one is visible would be a round trip to
  // show what the browser already holds.
  // ---------------------------------------------------------------

  function showTab(name) {
    document.body.dataset.tab = name;
    document.querySelectorAll("#tabs [data-tab]").forEach(function (tab) {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    });
  }

  showTab("playlist");

  // The tab strip sits outside the pane, so the pane cannot render it.
  // It publishes what the badge should say and this copies it across
  // after every swap — including the first, where the shell rendered the
  // pane inline and no swap ever happens.
  function paintBadge() {
    const pane = document.getElementById("imports-body");
    const badge = document.getElementById("imports-badge");
    if (!pane || !badge) return;

    badge.textContent = pane.dataset.badge || "";
  }

  paintBadge();
  document.body.addEventListener("htmx:afterSwap", paintBadge);

  // The junk figure in the header does what it looks like it offers.
  document.addEventListener("click", function (event) {
    if (event.target.closest("#junk-count")) {
      const box = document.querySelector('#filters input[name="junk"]');
      if (!box) return;

      box.checked = true;
      box.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }

    const tab = event.target.closest("#tabs [data-tab]");
    if (tab) {
      // The tabs switch the pane under them, and the workbench covers
      // that pane entirely — so asking for a tab is asking to be back in
      // the layout that has one. It doubles as the way out if the panel
      // itself ever fails to arrive.
      leaveWorkbench();
      showTab(tab.dataset.tab);
      return;
    }

    // A button that starts work in the other pane brings you to it.
    // Starting an import and leaving the listing on screen would hide
    // the one thing the click was about.
    const opener = event.target.closest("[data-open-tab]");
    if (opener) showTab(opener.dataset.openTab);
  });

  const audio = document.getElementById("audio");
  const bar = document.getElementById("player");
  const toolbar = document.getElementById("toolbar");
  const upNext = document.getElementById("player-next");
  const nextKey = document.getElementById("player-next-key");
  const nextText = document.getElementById("player-next-text");
  const nextTime = document.getElementById("player-next-time");
  const elapsed = document.getElementById("player-elapsed");
  const total = document.getElementById("player-total");
  const seek = document.getElementById("seek");
  const waveform = document.getElementById("waveform");
  const position = document.getElementById("player-position");
  const transport = document.getElementById("transport");
  const toggle = document.querySelector('[data-player-action="toggle"]');
  const volume = document.getElementById("volume");
  const volumeMute = document.getElementById("volume-mute");
  const volumeTrack = document.getElementById("volume-track");
  const filters = document.getElementById("filters");
  const playlistField = document.getElementById("playlist-field");
  const artistField = document.getElementById("artist-field");

  // {id, label, duration, junk} in play order, captured when the queue
  // is set.
  let queue = [];
  let index = -1;

  // Which way the queue is being walked. Pressing ← does not just step
  // back once: it turns the player round, and playback keeps going that
  // way when a track ends. The CLI behaves the same, and it is why the
  // preview below can be trusted.
  let direction = 1;

  function rows() {
    return Array.from(document.querySelectorAll("#list tr[data-song-id]"));
  }

  function queueFromRows() {
    return rows().map(function (row) {
      return {
        id: row.dataset.songId,
        label: row.dataset.label || "",
        duration: row.dataset.duration || "",
        junk: row.dataset.junk === "1",
      };
    });
  }

  // The song the listing was last scrolled to. Kept so that following
  // happens when the song changes and not when the list is repainted.
  let followed = null;

  function paint() {
    const current = queue[index];

    // Compared against null rather than reached through `current &&`.
    // classList.toggle takes an *optional* boolean: handed undefined it
    // treats the argument as absent and toggles instead of setting. With
    // nothing playing — which is every page load — that added `playing`
    // to all 927 rows at once. A strict comparison can only ever be true
    // or false, so the trap is gone rather than merely avoided.
    const currentId = current ? current.id : null;

    rows().forEach(function (row) {
      row.classList.toggle("playing", row.dataset.songId === currentId);
    });

    // Bring the playing row into view — once per song, not on every
    // repaint. A listing of 944 rows is 51 000 pixels tall, and after a
    // few skips the row that is lit is nowhere near the screen. Doing it
    // on every paint would yank the page back the moment you scrolled
    // off to look at something else; `nearest` then does nothing at all
    // when the row is already visible, so it never moves a list that
    // does not need moving.
    if (currentId !== followed) {
      followed = currentId;
      const playing = document.querySelector("#list tr.playing");
      if (playing) playing.scrollIntoView({ block: "nearest" });
    }

    // Three buttons that act on the selection. With nothing selected
    // they used to stay lit and do nothing at all, which reads as a
    // broken page rather than as an empty one.
    const empty = rows().length === 0;
    document.querySelectorAll("#toolbar [data-queue-action]").forEach(
      function (button) {
        button.disabled = empty;
        button.title = empty
          ? "Nothing to play — no song matches this filter"
          : button.dataset.hint || button.title;
      }
    );

    if (!current) {
      bar.classList.add("idle");
      if (toolbar) toolbar.classList.add("idle");
      nextKey.textContent = "NEXT";
      nextText.textContent = "Nothing playing";
      nextTime.textContent = "";
      upNext.title = "";
      transport.removeAttribute("data-direction");
      // The count the toolbar used to render server-side. It is the
      // same number the position turns into once something plays, so
      // nothing is lost by letting one slot carry both.
      //
      // Said against the library when the two differ, because otherwise
      // two numbers sat on the same screen meaning different things —
      // 944 up in the header, 8 down here — with nothing saying so.
      const total = rows().length;
      const library = Number(
        document.getElementById("counts")?.dataset.total || 0
      );
      position.textContent = !total
        ? ""
        : total === library
          ? total + " songs"
          : total + " of " + library;
      return;
    }

    bar.classList.remove("idle");
    if (toolbar) toolbar.classList.remove("idle");
    position.textContent = index + 1 + " / " + queue.length;

    const inCard = document.getElementById("workbench-position");
    if (inCard) inCard.textContent = position.textContent;

    // What is playing is already the inspector's whole job. What the bar
    // can say that nothing else does is what comes next.
    const following =
      queue[(index + direction + queue.length) % queue.length];
    nextKey.textContent = direction < 0 ? "NEXT ←" : "NEXT →";
    // The same fact on the buttons that set it. The toolbar's arrow is
    // at the top of the page and the transport is at the bottom, so
    // pressing ⏮ turned the player round with the only sign of it three
    // hundred pixels away from the hand that did it.
    transport.dataset.direction = direction < 0 ? "backward" : "forward";
    // The name first and the length after it, in its own element: they
    // are read at different moments — the name to know what is coming,
    // the length only if you are deciding whether to let it. Two
    // elements and not one string because they are also drawn
    // differently, and because the name is the part that truncates.
    nextText.textContent = following
      ? following.label + (following.junk ? " (JUNK)" : "")
      : "";
    nextTime.textContent = following ? following.duration : "";
    upNext.title = following
      ? nextKey.textContent + " " + nextText.textContent + "  " +
        nextTime.textContent
      : nextKey.textContent;
  }

  // Set when the inspector's form has edits nobody has saved. The panel
  // follows the playing song, and a track ending mid-sentence must not
  // wipe what you were typing.
  let dirty = false;

  // Workbench mode: same panel, full frame, one song at a time. The
  // cursor that walks the selection and the cursor that plays it are the
  // same one, so judging a song means hearing it.
  function inWorkbench() {
    return document.body.classList.contains("workbench-mode");
  }

  // How far ahead to identify. Shazam allows one call every 15s and the
  // throttle is now genuinely exclusive, so these queue up and arrive in
  // order. Three is about as far as a listener gets ahead of the worker.
  const PREFETCH = 3;

  function prefetch() {
    if (!inWorkbench()) return;

    for (let step = 1; step <= PREFETCH; step++) {
      const entry = queue[(index + step + queue.length) % queue.length];
      // Starting a job that is already running or finished is a no-op
      // server-side, so this needs no bookkeeping of its own.
      if (entry) window.htmx.ajax("POST", "/songs/" + entry.id + "/shazam", {
        target: "#prefetch",
        swap: "none",
      });
    }
  }

  // Whether the panel is describing the song that is playing. The two
  // cursors are allowed to differ — inspecting a song without cutting
  // what you are listening to is deliberate — but the page has to say
  // which one it is showing, or pressing play looks broken.
  function markInspectorCursor() {
    const panel = document.getElementById("inspector");
    if (!panel) return;

    const shown = panel.querySelector("[data-song-id]");
    const current = queue[index];

    // Reduced to two values and compared, the same way paint() does it.
    // classList.toggle takes an *optional* boolean, and anything that can
    // evaluate to undefined makes it toggle instead of set. Nothing
    // playing gives null, nothing shown gives "", and neither can equal
    // the other by accident.
    const currentId = current ? current.id : null;
    const shownId = shown ? shown.dataset.songId : "";

    panel.classList.toggle("is-playing", shownId === currentId);
  }

  document.body.addEventListener("htmx:afterSwap", markInspectorCursor);

  // The cover, crossfading.
  //
  // The panel is replaced wholesale on every song, so the outgoing
  // picture leaves with it and a transition has nothing to hold on to.
  // The way round it is to keep the old picture as the container's
  // background for the length of the fade and bring the new one up over
  // it — a crossfade rather than a blank square between two songs.
  //
  // The image is opaque by default and this makes it transparent, never
  // the other way round: if any of the below is skipped — no swap, an
  // error, a browser that never fires load — the cover is simply there,
  // which is what it was before any of this.
  let lastCover = "";

  // How long a transition on this element lasts, asked of the stylesheet
  // rather than repeated here. Two numbers that must agree are two
  // numbers that will not. Used by the cover's crossfade, which has to
  // outlast it, and by the board below, which turns at its halfway
  // point.
  function transitionMillis(element) {
    const value = getComputedStyle(element)
      .transitionDuration.split(",")[0].trim();
    const number = parseFloat(value) || 0;
    return value.endsWith("ms") ? number : number * 1000;
  }

  function crossfadeCover(box) {
    const img = box.querySelector(".cover");
    if (!img) {
      lastCover = "";
      return;
    }

    const outgoing = lastCover;
    lastCover = img.getAttribute("src");

    // Runs inside htmx's swap, before the browser has painted the new
    // markup, so the image never shows at full strength first.
    img.classList.add("arriving");
    if (outgoing) {
      box.style.backgroundImage = 'url("' + outgoing + '")';
    }

    function reveal() {
      img.classList.remove("arriving");
      // The picture underneath has done its work once the new one is
      // opaque. Left there it would show through the next transparent
      // cover, and every panel after that would carry a ghost.
      window.setTimeout(function () {
        box.style.backgroundImage = "";
      }, transitionMillis(img) + 80);
    }

    function giveUp() {
      img.classList.remove("arriving");
      box.style.backgroundImage = "";
      // This song has no art of its own, so there is nothing to fade
      // from next time either.
      lastCover = "";
    }

    // A cached picture is already complete, and a class added and
    // removed inside one frame transitions nothing — the element has
    // never been painted transparent.
    if (img.complete) {
      if (img.naturalWidth) window.requestAnimationFrame(reveal);
      else giveUp();
      return;
    }

    img.addEventListener("load", reveal, { once: true });
    img.addEventListener("error", giveUp, { once: true });
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    const swapped = event.target;
    if (!swapped || !swapped.querySelector) return;

    // Only when the swap actually brought a panel with it. Bound
    // unguarded, this ran on the imports poll — once a second, on
    // markup with no cover in it at all.
    const box = swapped.matches(".inspector-cover, .workbench-cover")
      ? swapped
      : swapped.querySelector(".inspector-cover, .workbench-cover");
    if (box) crossfadeCover(box);
  });

  function inspect(id) {
    // Held back by an edit nobody has saved. The panel deliberately
    // stops following the player here — but it used to do it in
    // silence, so the panel simply looked stuck on the wrong song.
    if (dirty) {
      document.getElementById("inspector").classList.add("holding-edits");
      return;
    }

    // The song *and* which panel is wanted. Comparing only the song let
    // the workbench open on a song the inspector was already showing and
    // load nothing at all: you got the plain panel full frame, with no
    // listing, no nav, and no Done — nothing on screen could leave the
    // mode, so the page had to be reloaded.
    const shown = document.querySelector("#inspector [data-song-id]");
    const showing = document.querySelector("#inspector .workbench")
      ? "workbench"
      : "inspector";
    const wanted = inWorkbench() ? "workbench" : "inspector";
    if (shown && shown.dataset.songId === id && showing === wanted) return;

    window.htmx.ajax("GET", "/fragments/" + wanted + "/" + id, "#inspector");
  }

  function play(i) {
    if (!queue.length) return;

    // Wrap rather than stop, the way the CLI's play loops its selection.
    index = (i + queue.length) % queue.length;
    audio.src = "/songs/" + queue[index].id + "/audio";
    loadWaveform(queue[index].id);
    warmWaveform();
    paint();

    // The song being judged is the song being heard: one cursor, not two.
    inspect(queue[index].id);
    markInspectorCursor();
    prefetch();

    audio.play().catch(function () {
      // Browsers refuse autoplay until the page has been interacted
      // with. Not an error — the controls are right there.
    });
  }

  function move(step) {
    if (!queue.length) return;

    // Stepping sets the direction, so the preview and what a finishing
    // track does next agree with each other.
    direction = step < 0 ? -1 : 1;
    play(index + step);
  }

  // Setting the queue: the visible listing becomes what plays, which is
  // what every music player does when you start a track from a view.
  // Whether the queue standing right now is in a random order. Not a
  // mode that changes what `move` does — shuffling reorders the queue
  // once, and this says so. Without it there is no way to tell a
  // shuffled queue from an ordered one.
  let inRandomOrder = false;

  function setQueue(entries, startAt, randomOrder) {
    queue = entries;
    inRandomOrder = Boolean(randomOrder);

    const button = document.querySelector('[data-queue-action="shuffle"]');
    if (button) button.setAttribute("aria-pressed", String(inRandomOrder));

    // A fresh selection plays forward, whichever way the last one ended.
    direction = 1;
    // A findIndex that missed returns -1, which play() would wrap round
    // to the last track. Start at the top instead.
    play(startAt > 0 ? startAt : 0);
  }

  function leaveWorkbench() {
    if (!inWorkbench()) return;

    document.body.classList.remove("workbench-mode");
    // Back to the ordinary panel for the song still playing. The music
    // does not stop: leaving a mode is not leaving the queue.
    if (queue[index]) {
      window.htmx.ajax(
        "GET", "/fragments/inspector/" + queue[index].id, "#inspector"
      );
    }
  }

  function shuffled(entries) {
    const out = entries.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  }

  audio.addEventListener("ended", function () {
    // Follows the direction rather than always going forward, so walking
    // backwards through a selection keeps working when you stop pressing
    // keys. This is what makes the preview honest.
    move(direction);
  });

  audio.addEventListener("play", function () {
    toggle.textContent = "⏸";
  });

  audio.addEventListener("pause", function () {
    toggle.textContent = "▶";
  });

  // ---------------------------------------------------------------
  // The transport
  //
  // Everything <audio controls> used to draw, drawn here instead: it
  // rendered a large rounded pill that no stylesheet can reach, and it
  // was the one shape on the page nobody had designed.
  // ---------------------------------------------------------------

  function clock(seconds) {
    if (!isFinite(seconds) || seconds < 0) return "0:00";

    const whole = Math.floor(seconds);
    const s = String(whole % 60).padStart(2, "0");
    const m = Math.floor(whole / 60) % 60;
    const h = Math.floor(whole / 3600);

    // Hours only when there are hours: a fixed 00:06:17 is three
    // characters of nothing, repeated on every row.
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + s : m + ":" + s;
  }

  // ---------------------------------------------------------------
  // The board
  //
  // One line under the title, holding two things in turn: the playlist,
  // always, and what Shazam answered about the release, when it answered
  // anything. Two lines was one too many; this is the same information
  // in the space of one.
  //
  // Split-flap, like a departures board. Each slot turns on its own a
  // beat after the one before, so the change reads as a mechanism rather
  // than as a redraw — and a slot already showing the right character
  // does not turn at all, which is both cheaper and what the real thing
  // does.
  //
  // The turn is a CSS transition rather than a keyframe animation, so the
  // reduced-motion rule at the foot of the stylesheet neutralises it and
  // the line simply changes.
  // ---------------------------------------------------------------

  const BOARD_HOLD = 5000;

  // Bumped on every new face. A turn in flight checks it before touching
  // a slot, so a song changed mid-flap does not finish spelling out the
  // previous one.
  let boardEra = 0;

  function boardFaces(board) {
    return [board.dataset.playlist || "", board.dataset.release || ""];
  }

  function showFace(board, text, turning) {
    // As many slots as the longer face, and rebuilt only when that
    // number changes — which is once, on arrival. Rebuilding per face
    // would drop every slot at once and there would be nothing left to
    // turn.
    //
    // The shorter face is padded out with spaces, so the board is always
    // the width of its longer face. That is why nothing shares this line
    // after it: see the templates.
    const width = Math.max(...boardFaces(board).map(function (face) {
      return face.length;
    }));
    let slots = Array.from(board.querySelectorAll(".slot"));

    if (slots.length !== width) {
      board.textContent = "";
      slots = [];
      for (let i = 0; i < width; i++) {
        const slot = document.createElement("span");
        slot.className = "slot";
        slot.textContent = " ";
        board.appendChild(slot);
        slots.push(slot);
      }
    }

    const era = ++boardEra;
    const half = turning ? transitionMillis(slots[0]) : 0;

    slots.forEach(function (slot, i) {
      const wanted = text[i] || " ";
      if (slot.textContent === wanted) return;

      window.setTimeout(function () {
        if (era !== boardEra) return;

        slot.classList.add("turning");
        window.setTimeout(function () {
          if (era !== boardEra) return;

          slot.textContent = wanted;
          // Green on arrival, grey once it has settled. Added with the
          // character and released after the flap has finished falling
          // back, so the accent is on for the whole of the turn and the
          // cooling starts from a character already in place.
          slot.classList.add("fresh");
          slot.classList.remove("turning");

          window.setTimeout(function () {
            if (era !== boardEra) return;

            slot.classList.remove("fresh");
          }, half);
        }, half);
      }, turning ? i * 18 : 0);
    });
  }

  function turnBoards() {
    document.querySelectorAll(".board[data-release]").forEach(
      function (board) {
        const showing = board.dataset.face === "release";
        board.dataset.face = showing ? "playlist" : "release";
        showFace(board, boardFaces(board)[showing ? 0 : 1], true);
      }
    );
  }

  let boardClock = 0;

  // Restarted rather than left running: a song clicked one second before
  // the tick would otherwise show its playlist for one second and then
  // flip, which reads as a glitch rather than as a cycle.
  function restartBoards() {
    if (boardClock) window.clearInterval(boardClock);
    boardClock = 0;

    document.querySelectorAll(".board").forEach(function (board) {
      board.dataset.face = "playlist";
      showFace(board, boardFaces(board)[0], false);
    });

    if (document.querySelector(".board[data-release]")) {
      boardClock = window.setInterval(turnBoards, BOARD_HOLD);
    }
  }

  restartBoards();
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.querySelector
        && event.target.querySelector(".board")) {
      restartBoards();
    }
  });

  // ---------------------------------------------------------------
  // The volume
  //
  // Notched, not continuous. #seek maps a click straight onto the
  // duration because there a pixel means a moment you asked for; a level
  // has no value to land on exactly, and twenty notches of five percent
  // are each three pixels wide — reachable with a mouse, and the same
  // number twice for the same gesture. It is the waveform's whole-pixel
  // step again: a round number beats an exact one.
  // ---------------------------------------------------------------

  const VOLUME_KEY = "pypl2mp3.volume";
  const VOLUME_STEP = 5;

  // What to come back to. Mute is not a level of its own — coming back
  // to silence is coming back to nothing — so the level it interrupted
  // is kept here and the audio element's own volume goes to zero.
  let level = 100;
  let muted = false;

  function paintVolume() {
    const shown = muted ? 0 : level;

    audio.volume = shown / 100;
    audio.muted = muted;

    volumeTrack.querySelector(".fill").style.width = shown + "%";
    volumeTrack.setAttribute("aria-valuenow", String(shown));
    volumeTrack.setAttribute("aria-valuetext", shown + "%");
    volumeMute.setAttribute("aria-pressed", String(muted));
    volumeMute.title = muted ? "Unmute" : "Mute";
    volumeMute.setAttribute("aria-label", volumeMute.title);
    volume.classList.toggle("is-muted", muted);
  }

  function rememberVolume() {
    try {
      localStorage.setItem(VOLUME_KEY, JSON.stringify({ level, muted }));
    } catch (error) {
      // Private browsing refuses localStorage, the same as the theme
      // switch. The control works for this page; it just will not be
      // remembered.
    }
  }

  function setVolume(next, nowMuted) {
    // To the nearest notch, and never off the ends.
    level = Math.max(
      0, Math.min(100, Math.round(next / VOLUME_STEP) * VOLUME_STEP)
    );
    // Silence is silence however it was reached. Dragging the track to
    // nothing left the speaker saying the sound was on while none came
    // out, and a second state that looks identical to the first is a
    // state nobody can act on.
    muted = Boolean(nowMuted) || level === 0;
    paintVolume();
    rememberVolume();
  }

  (function restoreVolume() {
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(VOLUME_KEY) || "null");
    } catch (error) {
      // Absent, refused, or written by an older version: full volume is
      // the right answer to all three.
    }
    // Not `stored.level || 100`: a stored zero is a choice, and falsy.
    const kept = stored && typeof stored.level === "number"
      ? stored.level
      : 100;
    setVolume(kept, Boolean(stored && stored.muted));
  })();

  function volumeFrom(event) {
    const box = volumeTrack.getBoundingClientRect();
    // Unmuting: pointing at a level is asking to hear it.
    setVolume(((event.clientX - box.left) / box.width) * 100, false);
  }

  volumeTrack.addEventListener("mousedown", function (event) {
    volumeFrom(event);

    function drag(moved) { volumeFrom(moved); }
    function stop() {
      window.removeEventListener("mousemove", drag);
      window.removeEventListener("mouseup", stop);
    }

    window.addEventListener("mousemove", drag);
    window.addEventListener("mouseup", stop);
  });

  // Arrows on the track, the same as on the seek bar, and stopping
  // propagation for the same reason: the document handler below would
  // otherwise change track as well.
  volumeTrack.addEventListener("keydown", function (event) {
    const up = event.key === "ArrowUp" || event.key === "ArrowRight";
    const down = event.key === "ArrowDown" || event.key === "ArrowLeft";
    if (!up && !down) return;

    event.preventDefault();
    event.stopPropagation();
    setVolume((muted ? 0 : level) + (up ? VOLUME_STEP : -VOLUME_STEP), false);
  });

  volumeMute.addEventListener("click", function () {
    // Muting keeps the level, so coming back comes back to where it was.
    // Coming back from a level of nothing has nowhere to return to, so
    // it returns to one notch instead of to silence again.
    if (muted) setVolume(level || VOLUME_STEP, false);
    else setVolume(level, true);
  });

  // On the whole group, so the speaker answers the wheel as well: it is
  // the larger of the two targets and aiming at the smaller one to turn
  // the sound down is a distinction nobody makes.
  volume.addEventListener("wheel", function (event) {
    event.preventDefault();
    const step = event.deltaY < 0 ? VOLUME_STEP : -VOLUME_STEP;
    setVolume((muted ? 0 : level) + step, false);
  }, { passive: false });

  // ---------------------------------------------------------------
  // The waveform
  //
  // Peaks come from the server, which computes them once per song and
  // keeps them in the MP3's tags. They are decoration over a control
  // that already works: nothing below touches how #seek is operated,
  // and a song whose peaks never arrive keeps the plain bar.
  // ---------------------------------------------------------------

  const brush = waveform.getContext("2d");
  let peaks = null;

  // Peaks reduced to the bars actually drawn, and how many that was.
  // Recomputing this every frame would be four hundred comparisons sixty
  // times a second for an answer that only changes when the box or the
  // song does.
  let shown = null;
  let shownCount = 0;

  // The loudest of each group, not their average. Averaging flattens a
  // snare into the quiet either side of it, and where the loud parts are
  // is the entire content of a waveform.
  function resample(count) {
    if (shown && shownCount === count) return shown;

    shownCount = count;
    // Never more bars than peaks: past that there is nothing left to
    // draw but detail that was never measured.
    if (count >= peaks.length) {
      shown = peaks;
      return shown;
    }

    const out = new Array(count);
    for (let i = 0; i < count; i++) {
      const from = Math.floor((i * peaks.length) / count);
      const to = Math.max(
        from + 1, Math.floor(((i + 1) * peaks.length) / count)
      );
      let top = 0;
      for (let j = from; j < to; j++) if (peaks[j] > top) top = peaks[j];
      out[i] = top;
    }
    shown = out;
    return shown;
  }

  // Skipping through a playlist leaves slower requests in flight behind
  // faster ones. Without this, the waveform you end up looking at is
  // whichever response happened to land last, not the song playing.
  let wanted = 0;

  function loadWaveform(id) {
    const mine = ++wanted;

    peaks = null;
    shown = null;
    shownCount = 0;
    seek.classList.remove("has-waveform");

    window.fetch("/songs/" + id + "/peaks")
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (mine !== wanted) return;

        peaks = data && data.length ? data : null;
        // The second argument is what makes this a set rather than a
        // toggle, and it has to be a real boolean: passing undefined
        // flips the class instead of clearing it.
        seek.classList.toggle("has-waveform", peaks !== null);
        paintWaveform();
        // Peaks routinely land after the song has started; without this
        // the picture is correct and frozen until the next pause.
        if (peaks && !audio.paused) startFollowing();
      })
      .catch(function () {
        // Offline, aborted, malformed: the plain bar is already there.
      });
  }

  // How the two halves relate: the reflection stands at a bit over a
  // third of the crest, and keeps a bit over half its colour.
  const MIRROR = 0.36;
  const MIRROR_INK = 0.55;

  // A bar and the step to the next one, in CSS pixels. These are what
  // stay fixed: the box is fluid — the window, the nav's clamp and the
  // workbench all change it — and dividing a fixed number of peaks
  // across it made the bars thinner as it narrowed. At six hundred
  // pixels four hundred bars came out half a pixel wide with no gap at
  // all, which is not a waveform, it is a smear. How many bars there are
  // is what gives way instead.
  const BAR = 3;
  const PITCH = 4;

  function paintWaveform() {
    if (!peaks) return;

    // Backing store in device pixels, or the bars come out blurred on
    // exactly the displays where a 2px bar needs to be sharp.
    const dpr = window.devicePixelRatio || 1;
    const box = waveform.getBoundingClientRect();
    const width = Math.round(box.width * dpr);
    const height = Math.round(box.height * dpr);
    if (!width || !height) return;

    if (waveform.width !== width) waveform.width = width;
    if (waveform.height !== height) waveform.height = height;

    // Read at paint time rather than cached: the theme switch, the
    // system following it, and a stylesheet edit all change these, and
    // there is no invalidation to forget.
    const palette = getComputedStyle(document.documentElement);
    const played = palette.getPropertyValue("--wave-played").trim();
    const rest = palette.getPropertyValue("--line-strong").trim();

    const length = audio.duration;
    const done = isFinite(length) && length > 0
      ? Math.max(0, Math.min(1, audio.currentTime / length))
      : 0;

    // Where the colour changes, to a fraction of a bar. Rounded to a
    // whole one, the boundary sat still for the two-thirds of a second
    // it takes a four-minute song to cross a bar, then jumped — and
    // that jump was the whole of what made this look mechanical.
    // As many bars as fit at the target step, and never more than there
    // are peaks: past that there is nothing left to draw but detail
    // nobody measured.
    const wanted = Math.max(1, Math.floor(width / (PITCH * dpr)));
    const count = Math.min(peaks.length, wanted);
    const bars = resample(count);

    const mark = done * bars.length;
    const edge = Math.min(Math.floor(mark), bars.length - 1);
    const into = Math.min(1, mark - edge);

    // A whole number of device pixels from one bar to the next, and that
    // is the point of it. Dividing the width by the count gives 4.0135,
    // and rounding each bar's own left edge got the edges crisp but not
    // the spacing: the accumulated fraction comes back as one five-pixel
    // gap every seventy-five bars, and a single wide gap in a field of
    // even ones is the first thing the eye finds. What a whole step
    // costs is the remainder — under one step, so at most three pixels —
    // left unused at the right edge, where nobody will find it.
    //
    // It also grows past the target on a box wide enough to want more
    // bars than there are peaks. The gap takes that slack; the bar keeps
    // its width, since bars that grow fat are what this exists to
    // prevent.
    const step = Math.max(1, Math.floor(width / count));
    const ink = Math.max(
      1, Math.min(Math.round(BAR * dpr), step - Math.round(dpr))
    );

    // The picture is asymmetric, and the lower half is not the negative
    // half of the signal — there is no negative half here, the peaks are
    // absolute loudness. It is the same number drawn a second time,
    // shorter and fainter.
    //
    // A truthful two-sided waveform would spend half its pixels
    // repeating the shape above them, because for music the two sides
    // are the same shape. Giving the crest the larger share buys that
    // resolution back at the same widget height, and the reflection
    // keeps the thing a centred drawing throws away: a baseline. Bars
    // standing on a line compare at a glance. Bars floating either side
    // of a middle have to be compared in two directions at once.
    const gap = Math.round(dpr);
    const crest = Math.round((height - gap) / (1 + MIRROR));
    const shadow = height - gap - crest;

    // Both halves of a run of bars in one pass each: the fill colour and
    // the alpha are the expensive part of a canvas, and setting them per
    // bar rather than per run is four hundred state changes a frame at
    // sixty frames a second.
    function band(from, to, colour, wash) {
      if (to <= from) return;
      brush.fillStyle = colour;

      brush.globalAlpha = wash;
      for (let i = from; i < to; i++) {
        // Silence still draws a hairline: the bar is the control, and a
        // gap in it would read as a gap in the song.
        const up = Math.max(dpr, bars[i] * crest);
        brush.fillRect(i * step, crest - up, ink, up);
      }

      brush.globalAlpha = wash * MIRROR_INK;
      for (let i = from; i < to; i++) {
        const down = Math.max(dpr, bars[i] * shadow);
        brush.fillRect(i * step, crest + gap, ink, down);
      }
    }

    brush.clearRect(0, 0, width, height);
    band(0, edge, played, 1);
    // The one bar the playhead is inside, drawn twice: the played colour
    // over the unplayed one, at the fraction of the bar already behind
    // it. That fraction is the whole of the smoothness — no animation
    // and no timer, only the position told instead of rounded.
    band(edge, edge + 1, rest, 1);
    band(edge, edge + 1, played, into);
    band(edge + 1, bars.length, rest, 1);
    brush.globalAlpha = 1;
  }

  // timeupdate fires four times a second. That is plenty for a clock and
  // far too coarse for a boundary meant to slide, so while the song
  // plays the picture repaints on the display's own cadence instead. The
  // browser stops calling this when the tab is hidden, so the cost is
  // only paid while somebody is looking at it.
  let frame = 0;

  function followPlayhead() {
    frame = 0;
    paintWaveform();
    if (!audio.paused) frame = window.requestAnimationFrame(followPlayhead);
  }

  function startFollowing() {
    if (!frame) frame = window.requestAnimationFrame(followPlayhead);
  }

  function stopFollowing() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    // One last frame, on the position it actually stopped at: the loop
    // ends between two repaints and would otherwise leave the boundary
    // up to a frame behind.
    paintWaveform();
  }

  audio.addEventListener("play", startFollowing);
  audio.addEventListener("pause", stopFollowing);
  audio.addEventListener("ended", stopFollowing);

  function paintTime() {
    const length = audio.duration;
    const done = audio.currentTime;
    const ratio = isFinite(length) && length > 0 ? done / length : 0;
    const percent = Math.max(0, Math.min(1, ratio)) * 100;

    elapsed.textContent = clock(done);
    total.textContent = clock(length);
    seek.querySelector(".fill").style.width = percent + "%";
    seek.setAttribute("aria-valuenow", Math.round(percent));
    paintWaveform();
  }

  audio.addEventListener("timeupdate", paintTime);
  audio.addEventListener("loadedmetadata", paintTime);
  audio.addEventListener("emptied", paintTime);

  // Ticking every row and unticking every row are the two things anyone
  // does to a list of thirty. Delegated, because the pane is replaced
  // wholesale on every poll and a handler bound to the box would go with
  // it.
  function rowBoxes() {
    return Array.from(
      document.querySelectorAll('#import-form input[name="songs"]')
    );
  }

  // Select all answers to the rows as well as commanding them. Left
  // one-way it stayed ticked after every row had been unticked, which
  // says the opposite of what the list shows.
  function paintPickAll() {
    const all = document.getElementById("pick-all");
    if (!all) return;

    const boxes = rowBoxes();
    const ticked = boxes.filter(function (box) { return box.checked; }).length;

    all.checked = ticked === boxes.length && boxes.length > 0;
    // Neither all nor none: the third state HTML already has for this.
    all.indeterminate = ticked > 0 && ticked < boxes.length;
  }

  document.addEventListener("change", function (event) {
    if (event.target.id === "pick-all") {
      rowBoxes().forEach(function (box) {
        box.checked = event.target.checked;
      });
      event.target.indeterminate = false;
      return;
    }

    if (event.target.name === "songs") paintPickAll();
  });

  document.body.addEventListener("htmx:afterSwap", paintPickAll);

  // Songs imported since the waveform existed carry their peaks already.
  // The ones that predate it compute theirs the first time they are
  // played — half a second, paid by somebody who is waiting for the
  // music. Asking for the next song's peaks now moves that half second
  // into the three minutes when nobody is waiting for anything, and the
  // answer is kept in the file, so it is paid once ever.
  //
  // Which song is next depends on the direction the queue is being
  // walked, the same as the readout in the toolbar.
  function warmWaveform() {
    if (queue.length < 2) return;

    const following =
      queue[(index + direction + queue.length) % queue.length];
    if (!following || following.id === queue[index].id) return;

    window.fetch("/songs/" + following.id + "/peaks").catch(function () {
      // Nothing to do and nothing to show: this is work done early, and
      // failing to do it early only means doing it on time.
    });
  }

  // The bar is fluid: the window, the nav's clamp and the workbench all
  // change its width, and a canvas does not reflow with its box.
  if (window.ResizeObserver) {
    new ResizeObserver(paintWaveform).observe(seek);
  }

  // Watching the attribute rather than hooking applyTheme: every way the
  // palette can change ends up here — the switch, the system moving
  // under "auto", anything added later — and there is no second place to
  // remember. Hooking the function would also have run it during setup,
  // before the canvas exists.
  new MutationObserver(paintWaveform).observe(document.documentElement, {
    attributeFilter: ["data-theme"],
  });

  function seekTo(event) {
    if (!isFinite(audio.duration) || audio.duration <= 0) return;

    const box = seek.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    audio.currentTime = Math.max(0, Math.min(1, ratio)) * audio.duration;
    paintTime();
  }

  seek.addEventListener("mousedown", function (event) {
    seekTo(event);

    function drag(moved) { seekTo(moved); }
    function stop() {
      window.removeEventListener("mousemove", drag);
      window.removeEventListener("mouseup", stop);
    }

    window.addEventListener("mousemove", drag);
    window.addEventListener("mouseup", stop);
  });

  // The bar is a slider, so arrows nudge the position rather than change
  // track. Stopping propagation is what keeps the document handler below
  // from doing both.
  seek.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    if (!isFinite(audio.duration)) return;

    event.preventDefault();
    event.stopPropagation();
    audio.currentTime = Math.max(
      0,
      Math.min(
        audio.duration,
        audio.currentTime + (event.key === "ArrowRight" ? 5 : -5)
      )
    );
    paintTime();
  });

  // A song that leaves the listing — filtered out, junkized — would keep
  // a stale row highlighted. The title stays put: it lives in the queue,
  // not in the row.
  const observer = new MutationObserver(paint);

  // Delegated: #list and #nav are replaced wholesale by htmx, so nothing
  // may hold a listener on an element inside them.
  document.addEventListener("click", function (event) {
    const navButton = event.target.closest("#nav button[data-playlist]");
    if (navButton) {
      playlistField.value = navButton.dataset.playlist;
      // Changing playlist changes which artists exist, and which entry
      // is current. The nav has to be rebuilt; the search box must not
      // rebuild it, which is why this is an event and not a trigger on
      // the form.
      artistField.value = "";
      filters.requestSubmit();
      document.body.dispatchEvent(new CustomEvent("playlistChanged"));
      return;
    }

    const artistButton = event.target.closest("#nav button[data-artist]");
    if (artistButton) {
      const picked = artistButton.dataset.artist;
      // Clicking the selected artist again clears it. Without that the
      // only way out of a preset would be to reload the page.
      artistField.value = artistField.value === picked ? "" : picked;
      artistButton.parentElement.parentElement
        .querySelectorAll("li.current")
        .forEach(function (li) {
          li.classList.remove("current");
        });
      if (artistField.value) {
        artistButton.parentElement.classList.add("current");
      }
      filters.requestSubmit();
      return;
    }

    const queueButton = event.target.closest("[data-queue-action]");
    if (queueButton) {
      const entries = queueFromRows();
      if (!entries.length) return;

      const action = queueButton.dataset.queueAction;
      if (action === "workbench") document.body.classList.add("workbench-mode");

      // Pressing it again reshuffles rather than putting the queue back
      // in order: the button says what order the queue is in, and after
      // a second press it is still a random one.
      const random = action === "shuffle";
      setQueue(random ? shuffled(entries) : entries, 0, random);
      return;
    }

    if (event.target.closest('[data-workbench="exit"]')) {
      leaveWorkbench();
      return;
    }

    const playerButton = event.target.closest("[data-player-action]");
    if (playerButton) {
      const action = playerButton.dataset.playerAction;
      if (action === "next") move(1);
      else if (action === "previous") move(-1);
      else if (action === "toggle") {
        if (!queue.length) {
          const entries = queueFromRows();
          if (entries.length) setQueue(entries, 0, false);
        } else if (audio.paused) {
          audio.play();
        } else {
          audio.pause();
        }
      }

      // Hand the focus back after a *mouse* click. Chrome does not ring a
      // button clicked with the pointer, but it rings it the moment the
      // next key is pressed — so clicking next and then reaching for the
      // arrow keys lit up a button that had nothing to do with the change:
      // the arrows are handled on the document.
      //
      // event.detail is the click count, and it is 0 when a button is
      // activated from the keyboard. Blurring only when it is not leaves
      // Tab and Enter working exactly as they did.
      if (event.detail > 0) playerButton.blur();

      return;
    }

    // Play what the panel is showing. It is not necessarily what the
    // queue is on — that is the whole point of being able to inspect a
    // song without cutting the one you are listening to.
    if (event.target.closest("#inspector .play-this")) {
      const shown = document.querySelector("#inspector [data-song-id]");
      if (!shown) return;

      const wanted = shown.dataset.songId;
      const entries = queueFromRows();
      const at = entries.findIndex(function (entry) {
        return entry.id === wanted;
      });

      if (at >= 0) {
        // In the listing: select it there, exactly as clicking its row
        // would, so the queue and what you can see stay the same thing.
        setQueue(entries, at, false);
      } else {
        // Filtered out of the listing, or imported into a view that does
        // not show it. Play it on its own rather than refuse: you asked
        // for this song, and the alternative is a button that sometimes
        // does nothing.
        setQueue(
          [{
            id: wanted,
            label: shown.dataset.label || "",
            duration: "",
            junk: false,
          }],
          0,
          false
        );
      }
      return;
    }

    // An imported song opens in the inspector. Only the rows that
    // finished carry an id: nothing reached the disk for the others, so
    // there is nothing to open, and a row that answers a click by doing
    // nothing is worse than one that plainly does not.
    const imported = event.target.closest(".import-row[data-song-id]");
    if (imported && !event.target.closest("button, a, input, label")) {
      // Staying put. The inspector sits above the tabs and is visible
      // from either of them, so switching would take you away from the
      // list you are reading to show you something you could already
      // see — and lose your place in a run of thirty rows.
      inspect(imported.dataset.songId);
      return;
    }

    // A click anywhere else on a row plays it, taking the listing as the
    // queue. Buttons and links inside the row keep their own meaning.
    const row = event.target.closest("#list tr[data-song-id]");
    if (row && !event.target.closest("button, a")) {
      const entries = queueFromRows();
      setQueue(
        entries,
        entries.findIndex(function (entry) {
          return entry.id === row.dataset.songId;
        }),
        false
      );
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.target.matches("input, textarea, select")) return;

    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        move(1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        move(-1);
        break;
      case "ArrowUp":
        event.preventDefault();
        setVolume((muted ? 0 : level) + VOLUME_STEP, false);
        break;
      case "ArrowDown":
        event.preventDefault();
        setVolume((muted ? 0 : level) - VOLUME_STEP, false);
        break;
      case " ":
        event.preventDefault();
        if (audio.paused) audio.play();
        else audio.pause();
        break;
      case "Tab":
        if (queue.length) {
          event.preventDefault();
          // Built from the queue rather than read off a link in the
          // bar: the inspector already carries that link, and one in
          // the player was a second copy of it.
          window.open(
            "https://youtu.be/" + queue[index].id, "_blank", "noopener"
          );
        }
        break;
      case "Escape":
        if (inWorkbench()) {
          event.preventDefault();
          leaveWorkbench();
        }
        break;
    }
  });

  // Enter saves and moves on. Allowed from inside a field, which the
  // guard above would otherwise swallow: the fast path is type, correct,
  // enter, without reaching for the mouse.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || !inWorkbench()) return;

    const form = document.querySelector("#inspector form");
    if (!form) return;

    event.preventDefault();
    form.requestSubmit();
  });

  // Anything typed in the inspector is unsaved work; stop following the
  // player until it is saved or the panel is replaced.
  document.addEventListener("input", function (event) {
    if (event.target.closest("#inspector")) dirty = true;
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "inspector") return;

    // A fresh panel carries no unsaved edits, and nothing left to hold.
    dirty = false;
    event.target.classList.remove("holding-edits");
  });

  // Shazam proposes; you decide. Filling the fields rather than writing
  // the tags is the point — it is confident about remixes it has never
  // heard.
  document.addEventListener("click", function (event) {
    const use = event.target.closest("[data-shazam-artist]");
    if (!use) return;

    const form = document.querySelector("#inspector form");
    if (!form) return;

    form.artist.value = use.dataset.shazamArtist;
    form.title.value = use.dataset.shazamTitle;
    form.cover_art_url.value = use.dataset.shazamCover || "";
    dirty = true;
  });

  // The ribbon appends, so starting the same job twice would stack two
  // elements sharing one id. Keep the newest: it is at least as fresh,
  // and a finished entry must not shadow a fresh run of the same job.
  const jobs = document.getElementById("jobs");
  if (jobs) {
    document.body.addEventListener("htmx:afterSwap", function (event) {
      if (event.target !== jobs) return;

      const seen = new Set();
      Array.from(jobs.children)
        .reverse()
        .forEach(function (entry) {
          if (!entry.id) return;
          if (seen.has(entry.id)) entry.remove();
          else seen.add(entry.id);
        });
    });
  }

  document.addEventListener("click", function (event) {
    const dismiss = event.target.closest("[data-dismiss-job]");
    if (!dismiss) return;

    dismiss.closest(".job-item").remove();

    // Every swap leaves the whitespace around its fragment behind, so
    // dismissing the last job left #jobs holding a dozen text nodes and
    // no elements. That is not `:empty`, so the rule that hides it no
    // longer matched — and because it spans the header's full width, it
    // went on reserving a flex line and the gap that separates one.
    if (jobs && !jobs.children.length) jobs.replaceChildren();
  });

  // 450 artists, nearly three quarters of them with a single song. The
  // list has to be complete to be a preset list, so it needs a way to
  // be narrowed. Purely local: the names are already in the page.
  // Diacritics are stripped both sides, the way the list is sorted:
  // typing "etienne" has to find "Étienne Daho".
  function plain(text) {
    return text
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }

  document.addEventListener("input", function (event) {
    if (event.target.id !== "artist-filter") return;

    const needle = plain(event.target.value.trim());
    document
      .querySelectorAll("#artist-list li")
      .forEach(function (row) {
        row.hidden = needle && !plain(row.textContent).includes(needle);
      });
  });

  // A save in the workbench means "done with this one". Advancing is
  // what makes the mode worth entering; stopping to admire the result
  // would be the old one-page-per-song rhythm again.
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (!inWorkbench()) return;
    if (!/\/fix$/.test(event.detail.requestConfig.path || "")) return;
    if (event.detail.requestConfig.verb !== "post") return;
    if (!event.detail.successful) return;

    dirty = false;
    move(1);
  });

  // Keep the address bar on the current selection so a reload restores
  // the view. The filter form is the query, so it is what gets read.
  document.addEventListener("htmx:afterRequest", function (event) {
    if (event.target !== filters) return;

    const params = new URLSearchParams(new FormData(filters));
    for (const [key, value] of Array.from(params)) {
      if (!value) params.delete(key);
    }
    const query = params.toString();
    window.history.replaceState(null, "", query ? "/?" + query : "/");
  });

  const list = document.getElementById("list");
  if (list) observer.observe(list, { childList: true, subtree: true });

  paint();

  // Arriving, the panel described nothing: "Select a song." The first
  // row is the obvious one to describe, so it describes that — and
  // describing a song is not playing it. The player stays silent until
  // asked, and the panel's own Play this button is what asks.
  //
  // Only when nothing is showing: a panel already filled by the server —
  // a reload during playback, a bookmarked song — is not overwritten.
  if (!document.querySelector("#inspector [data-song-id]")) {
    const first = rows()[0];
    if (first) inspect(first.dataset.songId);
  }
})();
