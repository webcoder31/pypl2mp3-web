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
  // Neighbours or fields. A class on the panel rather than two hidden
  // attributes, because the stylesheet already stacks the three
  // occupants of that cell and only needs telling which is up.
  // Named apart from the split-flap board's own `showFace` below, and
  // its attribute apart from that board's `data-face`. The first
  // version of this used both names: a second `function showFace` in
  // the same scope silently replaces the first, so the board's calls
  // arrived here with an element where a name was expected and this
  // switch's calls arrived there. Nothing threw, nothing was tested for
  // it, and the whole suite stayed green.
  function showPanelFace(name) {
    const body = document.getElementById("inspector-body");
    if (!body) return;

    body.classList.toggle("showing-edit", name === "edit");
    document.querySelectorAll("#inspector [data-shows]").forEach(
      function (button) {
        button.setAttribute(
          "aria-pressed", String(button.dataset.shows === name)
        );
      }
    );
  }

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

    // Which of the two shares the cell: the five nearest, or the fields
    // that change this song's tags.
    const face = event.target.closest("[data-shows]");
    if (face) {
      showPanelFace(face.dataset.shows);
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

  // Where you are in the run, repeated inside the workbench card. The
  // toolbar's own readout is off screen in that mode.
  function showPosition() {
    const inCard = document.getElementById("workbench-position");

    if (inCard) inCard.textContent = bar.classList.contains("idle")
      ? "" : position.textContent;
  }
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
        // Two, and they answer different questions. `id` is the video,
        // which is what the server is asked about this song. `key` is
        // the playlist and the video together, which is what says *which
        // row* — eight songs here sit in two playlists at once, and
        // everything keyed on the video treated the pair as one.
        id: row.dataset.songId,
        key: row.dataset.songKey,
        label: row.dataset.label || "",
        duration: row.dataset.duration || "",
        junk: row.dataset.junk === "1",
      };
    });
  }

  // The song the listing was last scrolled to. Kept so that following
  // happens when the song changes and not when the list is repainted.
  let followed = null;


  // What the row's one button says. Take out on a song you asked for,
  // Play next on any other — and that label is the only thing saying you
  // put it there: the listing is in play order, so a row following the
  // one playing looks the same whether you asked for it or it was simply
  // next, and the button is where the difference can be acted on.
  //
  // Written only when it differs. A MutationObserver on #list calls
  // `paint`, so anything paint touches inside the listing calls paint
  // again — `textContent = x` replaces the node even when x is what was
  // already there, and that is a childList record.
  function showAsk(row, queued) {
    const button = row.querySelector("[data-play-next]");
    if (!button) return;

    const label = queued ? "Take out" : "Play next";
    const title = queued
      ? "Put it back where it was"
      : "Play it after the one playing";

    if (button.textContent !== label) button.textContent = label;
    if (button.title !== title) button.title = title;
  }

  // Which of the five neighbours is the row that actually plays next.
  //
  // Kept here rather than asked of the server, because lining a song up
  // by hand makes it the next row a tenth of a second later — and a
  // panel still naming the old one would be saying something false
  // about what is about to play. The walk puts the nearest there; a
  // click puts whatever you chose there; this says which, either way.
  function markWhatIsNext(all, asked) {
    const panel = document.getElementById("neighbours");
    if (!panel) return;

    const offered = panel.querySelectorAll(".neighbour");
    if (!offered.length) return;

    const playing = queue[index] ? queue[index].key : null;
    const at = all.findIndex(function (row) {
      return row.dataset.songKey === playing;
    });
    const after = at >= 0 && all[at + 1] ? all[at + 1].dataset.songKey : null;

    offered.forEach(function (one) {
      const key = one.dataset.songKey;

      one.classList.toggle("is-next", key === after);
      one.classList.toggle("queued", asked.has(key));
      // The same two-state button the listing has, and the same
      // function deciding what it says: one button with one meaning,
      // and no second place for the two to disagree about what a click
      // does.
      showAsk(one, asked.has(key));
    });
  }

  function paint() {
    const current = queue[index];

    // Compared against null rather than reached through `current &&`.
    // classList.toggle takes an *optional* boolean: handed undefined it
    // treats the argument as absent and toggles instead of setting. With
    // nothing playing — which is every page load — that added `playing`
    // to all 927 rows at once. A strict comparison can only ever be true
    // or false, so the trap is gone rather than merely avoided.
    //
    // The key and not the id: a video held by two playlists is two rows,
    // and lighting both said the song was playing twice.
    const currentKey = current ? current.key : null;

    const all = rows();

    // The listing *is* the play order. There is no other, so there is
    // nothing to choose between and nothing to number: a row that comes
    // after another comes after it, which is the whole of what a rank
    // column and a sort switch were there to explain.
    lay(all, inPlayOrder(all));

    const asked = new Set(lineupStanding().map(function (song) {
      return song.key;
    }));

    all.forEach(function (row) {
      const queued = asked.has(row.dataset.songKey);

      row.classList.toggle("playing", row.dataset.songKey === currentKey);
      // A real boolean, not a value that could be undefined: given one,
      // classList.toggle treats the argument as absent and toggles.
      row.classList.toggle("queued", queued);
      showAsk(row, queued);
    });

    markWhatIsNext(all, asked);

    justMoved = null;

    // Bring the playing row into view — once per song, not on every
    // repaint. A listing of 944 rows is 51 000 pixels tall, and after a
    // few skips the row that is lit is nowhere near the screen. Doing it
    // on every paint would yank the page back the moment you scrolled
    // off to look at something else; `nearest` then does nothing at all
    // when the row is already visible, so it never moves a list that
    // does not need moving.
    if (currentKey !== followed) {
      followed = currentKey;
      const playing = document.querySelector("#list tr.playing");
      if (playing) playing.scrollIntoView({ block: "nearest" });
    }

    // Three buttons that act on the selection. With nothing selected
    // they used to stay lit and do nothing at all, which reads as a
    // broken page rather than as an empty one.
    const empty = rows().length === 0;
    // Every one of them, wherever it sits: Workbench is on the tab row
    // now and would otherwise stay lit over an empty listing — which is
    // the exact thing this loop was written to stop.
    document.querySelectorAll("[data-queue-action]").forEach(
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

    showPosition();

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

  // Held back for the same reason the card's own request is: a bet that
  // you will stay long enough to read the answer. Stepping again before
  // it fires cancels it, so walking through a run places no bets at all.
  //
  // Long, and deliberately longer than the card's own dwell. One caller
  // reaches Shazam at a time and the next may not go for fifteen
  // seconds, so a bet placed too eagerly is not free — it is fifteen
  // seconds in front of the song you are actually looking at.
  let prefetchClock = 0;

  function prefetch() {
    if (prefetchClock) window.clearTimeout(prefetchClock);
    prefetchClock = 0;

    if (!inWorkbench()) return;

    prefetchClock = window.setTimeout(placeBets, 2500);
  }

  function placeBets() {
    if (!inWorkbench()) return;

    for (let step = 1; step <= PREFETCH; step++) {
      const entry = queue[(index + step + queue.length) % queue.length];
      // Starting a job that is already running or finished is a no-op
      // server-side, so this needs no bookkeeping of its own.
      if (entry) window.htmx.ajax("POST", "/songs/" + entry.key + "/shazam", {
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
    const currentKey = current ? current.key : null;
    const shownKey = shown ? shown.dataset.songKey : "";

    panel.classList.toggle("is-playing", shownKey === currentKey);
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

  function inspect(key) {
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
    const shown = document.querySelector("#inspector [data-song-key]");
    const showing = document.querySelector("#inspector .workbench")
      ? "workbench"
      : "inspector";
    const wanted = inWorkbench() ? "workbench" : "inspector";
    if (shown && shown.dataset.songKey === key && showing === wanted) return;

    // Through the filter form, because the panel now carries this
    // song's neighbours and those may only offer what the listing
    // holds. The workbench has none and ignores them.
    window.htmx.ajax("GET", "/fragments/" + wanted + "/" + key, {
      target: "#inspector",
      swap: "innerHTML",
      source: document.getElementById("filters"),
    });
  }

  function play(i) {
    if (!queue.length) return;

    const leaving = queue[index] ? queue[index].key : null;

    // Wrap rather than stop, the way the CLI's play loops its selection.
    index = (i + queue.length) % queue.length;

    // The card you just left is not going to be read, and its
    // identification would take the fifteen-second throttle in front of
    // the one you stopped on. Told to the server rather than left to
    // finish: cancelling reaches the job inside its wait.
    if (inWorkbench() && leaving && leaving !== queue[index].key) {
      window.htmx.ajax("POST", "/songs/" + leaving + "/shazam/cancel", {
        target: "#prefetch",
        swap: "none",
      });
    }
    audio.src = "/songs/" + queue[index].key + "/audio";
    loadWaveform(queue[index].key);
    warmWaveform();
    paint();

    // The song being judged is the song being heard: one cursor, not two.
    inspect(queue[index].key);
    markInspectorCursor();
    prefetch();

    audio.play().catch(function () {
      // Browsers refuse autoplay until the page has been interacted
      // with. Not an error — the controls are right there.
    });
  }

  // `asked` is the user stepping — Skip, the transport, the arrows — as
  // against a track simply ending.
  function move(step, asked) {
    if (!queue.length) return;

    // In the workbench an asked-for step is the answer to "are you done
    // with this one": Skip means do not save it, so whatever is in the
    // fields goes with it. The hold is for the passive case, where a
    // track ending mid-sentence must not wipe what you were typing.
    //
    // It mattered most here. Taking Shazam's answer marks the form
    // dirty, so Use this and then Skip left the audio walking on with
    // the card stuck behind it — and the card has no room for the line
    // that tells the panel's reader it is holding, so nothing said so.
    if (asked && inWorkbench()) forgetEdits();

    // Stepping sets the direction, so the preview and what a finishing
    // track does next agree with each other.
    direction = step < 0 ? -1 : 1;
    play(index + step);
  }

  // Setting the queue: the visible listing becomes what plays, which is
  // what every music player does when you start a track from a view.

  // The rows asked for by hand, in the order they were asked for. Keys
  // and not video ids: two copies of one video are two rows and two
  // places in the queue, and a run holding the video could not say which
  // of them it meant.
  //
  // The songs asked for by hand, in the order they were asked for. Not a
  // second queue: they are moved into place in the one queue, so the
  // count in the toolbar goes on meaning what it says and no song is
  // ever in the list twice.
  //
  // Ids, and not the index the run ends at. That was the first version
  // and it was wrong in a way only the cursor moving backwards shows:
  // one press of ← and every song between the new position and the
  // pointer was inside the run, so a song nobody had asked for took the
  // head of it and the next request came out one too high. A rank has to
  // come from the run, never from the distance to the playing song.
  let lineup = [];

  // For each song in the run, the key of the entry it stood in front of
  // when it was taken out of its place. Taking it back out of the run
  // means putting it back there — an index would not do, because every
  // later request moves things and an index measured before that is a
  // different place afterwards. A key is the same song wherever it went.
  //
  // Its successor and not its predecessor: a song at the end of the
  // queue has none, which is the one case that needs no lookup — it
  // goes back to the end.
  const returns = new Map();

  // The run as it stands: those still in front of the playing song, in
  // the order the queue holds them. Anything else has been played, or
  // moved, or went with the selection that held it.
  function lineupAhead() {
    return lineup
      .map(function (key) {
        return {
          key: key,
          at: queue.findIndex(function (entry) { return entry.key === key; }),
        };
      })
      .filter(function (song) { return song.at > index; })
      .sort(function (a, b) { return a.at - b.at; });
  }

  // The rows in the order the queue plays them.
  //
  // Walked rather than looked up: eight songs in this library sit in two
  // playlists at once, so one id names two rows — and in the queue those
  // are two entries and two places, not one. Each entry claims the next
  // row still unclaimed that carries its id.
  //
  // Whatever the queue does not name goes behind, keeping the order it
  // had. The queue is a snapshot of the rows at the moment you pressed
  // play, so a listing filtered since then holds songs it never saw.
  function inPlayOrder(all) {
    const waiting = new Map();

    all.forEach(function (row) {
      const key = row.dataset.songKey;

      if (!waiting.has(key)) waiting.set(key, []);
      waiting.get(key).push(row);
    });

    const out = [];
    const claimed = new Set();

    queue.forEach(function (entry) {
      const rows = waiting.get(entry.key);

      if (rows && rows.length) {
        const row = rows.shift();
        out.push(row);
        claimed.add(row);
      }
    });

    all.forEach(function (row) {
      if (!claimed.has(row)) out.push(row);
    });

    return out;
  }

  // How long a row takes to travel to its new place, and how long the
  // one you moved stays lit after it lands.
  //
  // 220ms: this stylesheet speaks two lengths — a tenth of a second for
  // everything utilitarian, three quarters for the cover's dissolve,
  // "the one place the page is asked to be looked at". A row crossing
  // three hundred pixels in 120ms is a blink; 220 is seen without being
  // waited for.
  // How long a row takes to travel to its new place, and how long the
  // one you moved stays lit after it lands.
  //
  // 220ms: this stylesheet speaks two lengths — a tenth of a second for
  // everything utilitarian, three quarters for the cover's dissolve,
  // "the one place the page is asked to be looked at". A row crossing
  // three hundred pixels in 120ms is a blink; 220 is seen without being
  // waited for.
  const SLIDE_MS = 220;
  const MAX_SLIDE_MS = 520;
  const LANDED_MS = 900;

  // Rows put back where they were and then let go — the browser
  // interpolates the journey they did not make. FLIP, with the row you
  // asked for lit where it lands: the run it joins is two or three rows
  // that look alike, and after a slide the eye needs telling which one
  // was yours.
  //
  // Both in one declaration, because `transition` is a single property
  // and does not merge. The tint lived in a class of its own first, and
  // an inline `transition: transform` from the slide silently replaced
  // it: the background went from full to nothing between two frames
  // with no fade at all. That took measuring to find — the class was on
  // the row the whole time.
  //
  // Transitions rather than keyframe animations, deliberately: the rule
  // at the foot of the stylesheet neutralises transition durations under
  // prefers-reduced-motion and walks straight past animations, so this
  // way both are instant for anyone who asked for that.
  //
  // Inline styles, so every write here is an attribute change. The
  // MutationObserver on #list watches childList, and would otherwise
  // call `paint` at each of them.
  function slide(seen, lit) {
    const touched = [];
    const room = window.innerHeight;
    const margin = room / 2;
    let travel = 0;
    let mover = null;

    // Every position first, and only then the transforms.
    //
    // Reading a row's box and writing its transform in the same turn,
    // nine hundred times over, asks the browser to lay the whole table
    // out again between each pair: a Play next on a row far down the
    // listing cost 0.6 to 0.8 seconds, measured, and the radio's first
    // steer over two. Separated, the reads settle one layout and the
    // writes need none.
    const moved = [];
    seen.forEach(function (was, row) {
      moved.push([row, was, row.getBoundingClientRect()]);
    });

    moved.forEach(function (found) {
      const row = found[0];
      const was = found[1];
      const box = found[2];
      const mine = row.dataset.songKey === lit;

      // Only what can be watched. A song four hundred rows down moves
      // four hundred rows of neighbours, and setting a transform on all
      // of them is the pause before anything happens at all — none of
      // them is on screen to be seen doing it. A row earns an animation
      // by starting or ending where the eye is.
      const watched =
        (was > -margin && was < room + margin) ||
        (box.bottom > -margin && box.top < room + margin);

      if (!watched) return;

      const shift = was - box.top;

      if (!shift && !mine) return;

      // Where the transition should end, which is not always where the
      // row is going.
      //
      // A song four hundred rows down is twenty thousand pixels from its
      // new place, and its new place is nowhere near the screen: you are
      // looking at the row you just clicked. Animating the arrival
      // animates it off screen, and all you see is the row vanish from
      // under the pointer — which is what this looked like for three
      // goes at it.
      //
      // So the visible half of the journey is the one that gets
      // animated: the row holds its old place and travels one screen
      // towards where it is going, which is the direction you need told.
      // The rest is covered instantly, off screen, unwatched.
      let target = 0;

      if (mine && Math.abs(shift) > room) {
        target = shift - (shift > 0 ? room : -room);
      }

      row.style.transition = "none";
      row.style.transform = "translateY(" + shift + "px)";

      if (mine) {
        // A body for the journey. Without it the row is text sliding
        // over text — the movement happens and cannot be read.
        row.classList.add("moving");
        mover = row;
      }

      travel = Math.max(travel, Math.abs(shift - target));
      touched.push([row, target]);
    });


    if (!touched.length) return;

    // Long enough to be followed. A fixed 220ms is right for a row
    // stepping aside and far too fast for one crossing the window: a
    // thousand pixels in 220ms is seventy-five a frame, which reads as a
    // flicker. Scaled by the distance actually travelled, and capped so
    // that nothing ever feels slow.
    const ms = Math.min(
      MAX_SLIDE_MS, Math.max(SLIDE_MS, Math.round(travel * 0.55))
    );

    // One frame. A transition runs from the style of the last frame the
    // browser painted, and the values above were set in the click's own
    // task — so a frame carrying them is drawn before this callback,
    // which belongs to the next one. Two frames worked as well and cost
    // another sixteen milliseconds before anything moved.
    window.requestAnimationFrame(function () {
      touched.forEach(function (pair) {
        pair[0].style.transition = "transform " + ms + "ms ease";
        pair[0].style.transform = pair[1]
          ? "translateY(" + pair[1] + "px)"
          : "";
      });

      window.setTimeout(function () {
        touched.forEach(function (pair) {
          // Cleared, not transitioned: for a row that only travelled the
          // visible screen's worth, this is the rest of its journey, and
          // it happens where nobody is looking.
          pair[0].style.transition = "";
          pair[0].style.transform = "";
        });

        // Landed: the body it travelled in comes off, and the tint it
        // arrives with fades. Two stages rather than one declaration —
        // the journey wants an opaque card and the arrival wants a
        // colour draining away, and a single transition cannot be both.
        if (mover) land(mover);
      }, ms);
    });
  }

  // Where it landed, lit for a moment. The run it joins is two or three
  // rows that look alike, and after a journey the eye needs telling
  // which one was yours.
  function land(row) {
    row.classList.remove("moving");
    row.style.transition = "none";
    row.style.background = "var(--accent-soft)";

    // A transition runs from the style of the last frame the browser
    // painted, so the tint has to be on screen before it is taken off.
    // The cover's dissolve names the same trap.
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        row.style.transition = "background " + LANDED_MS + "ms ease-out";
        row.style.background = "";

        window.setTimeout(function () {
          row.style.transition = "";
        }, LANDED_MS);
      });
    });
  }

  // Put them there — and only when they are not there already.
  //
  // A MutationObserver on #list calls `paint`, so a reorder that runs
  // whether or not anything moved calls itself for ever: taking a node
  // out and putting it back where it was is still a childList record.
  // The whole listing moves in one fragment, so the observer sees one
  // batch rather than 944.
  function lay(all, wanted) {
    let settled = all.length === wanted.length;

    for (let at = 0; settled && at < wanted.length; at++) {
      settled = all[at] === wanted[at];
    }

    if (settled || !wanted.length) return;

    // Where each row is now, for the slide below — but only when a
    // click is what moved something. Shuffling sends every row to an
    // unrelated place, and nine hundred rows crossing each other says
    // nothing you could follow; an insertion is one row travelling and
    // a handful stepping aside, which is exactly what a slide shows.
    //
    // All of them, not the ones on screen. Filtering to the viewport
    // first looked like the saving: it is 1.4ms for all 944, measured,
    // and a row asked for from below the fold has its *arrival* on
    // screen and nothing to be inverted from — so it jumped, which is
    // the thing this exists to stop.
    const seen = new Map();

    if (justMoved) {
      all.forEach(function (row) {
        seen.set(row, row.getBoundingClientRect().top);
      });
    }

    // Only the rows that are out of place. Rebuilding the listing into
    // a fragment and re-appending it moved all 944 nodes whatever had
    // changed: 94ms of node churn and 138ms of layout behind it,
    // measured — a quarter of a second before the slide could begin, for
    // one song changing place. Walking the wanted order against what is
    // there turns an insertion into a single insertBefore.
    const parent = wanted[0].parentNode;

    // Out of the document while the rows are rearranged, when nothing
    // is being animated. Every insertBefore on an attached table asks
    // the browser to lay it out again, and replanning the radio's walk
    // moves nine hundred of them: two seconds, measured, against
    // twenty-odd detached. It cannot be done when a slide is due — the
    // animation has to invert against positions the rows actually hold.
    const holder = justMoved ? null : parent.parentNode;
    const after = holder ? parent.nextSibling : null;
    if (holder) holder.removeChild(parent);

    let cursor = parent.firstElementChild;

    wanted.forEach(function (row) {
      if (cursor === row) {
        cursor = cursor.nextElementSibling;
        return;
      }

      parent.insertBefore(row, cursor);
    });

    if (holder) holder.insertBefore(parent, after);

    slide(seen, justMoved);
  }

  // The row a click has just moved, so the tint lands on it and on
  // nothing else. Read by `lay`, and cleared by `paint` once the move it
  // describes has been drawn.
  let justMoved = null;

  // The run as it stands, pruned to what is still in front of the song
  // playing. Called from `paint`, which runs when the cursor has just
  // moved: a song the run has been played past is no longer in it.
  function lineupStanding() {
    const ahead = lineupAhead();

    lineup = ahead.map(function (song) { return song.key; });
    ahead.forEach(function (song) { song.entry = queue[song.at]; });

    return ahead;
  }


  function setQueue(entries, startAt) {
    queue = entries;
    // A new selection is a new intent; whatever was lined up in the old
    // one is not in this queue at all.
    lineup = [];
    returns.clear();

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
        "GET", "/fragments/inspector/" + queue[index].key, "#inspector"
      );
    }
  }

  // Line a song up, or take it back out. Which of the two it does is
  // read off the run itself rather than off an attribute that could
  // disagree with the label — and it lives here rather than in the
  // click handler because two places now reach it: the button, and the
  // row around it.
  function lineUpOrTakeOut(key) {
    if (!key) return;

    if (lineup.indexOf(key) === -1) {
      playNext(key);
      replanFrom(key);
      return;
    }

    unqueue(key);
    // And the walk goes back to leading from the song playing. Putting
    // the song back where it came from cannot restore the course,
    // because the course was rebuilt around it — so the undo has to be
    // a replan too, or taking a song out would leave the radio
    // following a route chosen for a song no longer on it.
    if (queue[index]) replanFrom(queue[index].key);
  }

  // Play this one after the one playing — and after the last one asked
  // for before it, so picking three songs out of a listing plays them in
  // the order they were picked rather than in reverse.
  function playNext(key) {
    // Nothing playing, so there is no "next" for it to come after. Take
    // the listing and start there, exactly as clicking the row does.
    if (!queue.length) {
      const entries = queueFromRows();
      setQueue(entries, entries.findIndex(function (entry) {
        return entry.key === key;
      }), false);
      return;
    }

    const from = queue.findIndex(function (entry) { return entry.key === key; });

    // Already the one playing: nothing to line up.
    if (from === index) return;

    let entry;

    if (from === -1) {
      // Not in the queue at all — a row from a listing that has been
      // filtered since the queue was taken.
      entry = queueFromRows().find(function (row) { return row.key === key; });
      if (!entry) return;
    } else {
      // Moved and not copied. A copy would play the song twice and make
      // the toolbar's "12 / 79" a count of something other than the
      // selection.
      entry = queue[from];
      queue.splice(from, 1);
      // Whatever now stands at that index is what this song stood in
      // front of. Read after the removal, so it is the successor and
      // not the song itself.
      returns.set(key, queue[from] ? queue[from].key : null);
      // Taken out from in front of it, the cursor shifts back one.
      // Removing first and working the destination out afterwards is
      // what keeps this correct for a song that was already behind the
      // playing one.
      if (from < index) index -= 1;
    }

    // Asked for again: it keeps one place in the run, and that place is
    // the newest — a second request is a request.
    lineup = lineup.filter(function (other) { return other !== key; });

    // Behind the last one still ahead of the playing song, or behind the
    // playing song when the run has none left. Worked out after the
    // removal, so the positions are the ones the queue actually has.
    const ahead = lineupAhead();
    const at = (ahead.length ? ahead[ahead.length - 1].at : index) + 1;

    queue.splice(at, 0, entry);
    // Rebuilt from what is still standing, which is also what keeps the
    // list from growing for the life of the page.
    lineup = ahead.map(function (song) { return song.key; }).concat(key);

    // Asked to be played next, so the queue is going forward. A track
    // ending follows `direction`, and walking backwards through a
    // selection would never reach what was just lined up.
    direction = 1;
    justMoved = key;
    paint();
  }



  // Out of the run, and back where it stood. The one thing no version of
  // this could do until now: a song asked for by mistake could only be
  // played or skipped.
  function unqueue(key) {
    const from = queue.findIndex(function (entry) { return entry.key === key; });
    if (from === -1 || from === index) return;

    const entry = queue[from];
    const before = returns.get(key);

    queue.splice(from, 1);
    if (from < index) index -= 1;

    lineup = lineup.filter(function (other) { return other !== key; });
    returns.delete(key);

    // In front of what it used to be in front of — but only if that
    // song is still where it was.
    //
    // Ask for two songs that sit next to each other in the listing, and
    // the first records the second as its way home. The second is then
    // lifted to the front too, so following it home follows it to the
    // front: the song came back out of the run and went straight back to
    // where the run is, unmarked and apparently stuck. Each song the
    // chain passes recorded its own way home, so following it past
    // everything still lifted arrives at a song that never moved.
    let anchor = before;
    const passed = new Set([key]);

    while (anchor && lineup.indexOf(anchor) !== -1 && !passed.has(anchor)) {
      passed.add(anchor);
      anchor = returns.get(anchor);
    }

    // Nothing left to come back to — filtered away, or the run reached
    // the end of the queue. The end is where a song nobody has asked
    // anything about belongs.
    const at = anchor === null || anchor === undefined
      ? queue.length
      : queue.findIndex(function (other) { return other.key === anchor; });

    queue.splice(at === -1 ? queue.length : at, 0, entry);
    justMoved = key;
    paint();
  }

  // Which of the three orders the listing is in, and choosing one starts
  // it. Two of them are the server's to render — the playlist's own and
  // the alphabet — so those are a refetch; shuffling needs no round trip
  // and no repository, only the rows already here.
  //
  // A reset, and it could be nothing else: an order *is* a queue, so
  // rebuilding one discards whatever was lined up by hand. `setQueue`
  // clears the run and the ways home with it.
  //
  // Not remembered across reloads. On arrival nothing is playing and the
  // listing is in the server's own order, so a switch lit on "shuffle"
  // from a previous visit would be describing something that is not
  // there.
  //
  // Read from the field the shell rendered rather than assumed, so a
  // reload with an order in the address agrees with the icon lit.
  const orderField = document.getElementById("order-field");
  let playOrder = orderField ? orderField.value || "youtube" : "youtube";

  // True only for the moment between asking the server for a listing in
  // a new order and its arrival. Every other listing swap — a filter
  // keystroke, a save, a playlist change — must leave the queue where it
  // is; this one is the whole point of the request.
  let orderAsked = false;

  function showOrder() {
    document.querySelectorAll("#orders button").forEach(function (button) {
      button.setAttribute(
        "aria-pressed", String(button.dataset.playOrder === playOrder)
      );
    });
  }

  // Each song's nearest few, as the radio listing brings them: the
  // positions the browser needs to replan a walk without asking.
  let radioMap = null;

  function readRadioMap() {
    const blob = document.getElementById("radio-map");
    radioMap = null;
    if (!blob) return;

    try {
      const said = JSON.parse(blob.textContent);
      const at = new Map();
      said.keys.forEach(function (key, position) { at.set(key, position); });
      radioMap = { keys: said.keys, near: said.near, at: at };
    } catch (error) {
      // A listing that arrives without a usable table is a listing the
      // radio simply cannot replan. It still plays.
      radioMap = null;
    }
  }

  // Walk the rest of the queue again from the song just chosen.
  //
  // This is what makes steering mean something: without it the radio
  // plays your song and then returns to the course it was already on,
  // which is not what "play this next" suggests.
  //
  // Reorders the queue and leaves the listing to `paint`, so the rows
  // move by the same slide a hand-queued song already uses.
  function replanFrom(key) {
    if (playOrder !== "radio" || !radioMap) return;

    const from = queue.findIndex(function (entry) {
      return entry.key === key;
    });
    if (from < 0) return;

    const head = queue.slice(0, from + 1);
    const rest = queue.slice(from + 1);
    if (rest.length < 2) return;

    const waiting = new Map();
    rest.forEach(function (entry) { waiting.set(entry.key, entry); });

    const walk = [];
    let here = key;
    // Where the fallback has got to, so that exhausting a song's eight
    // near the end of the walk does not rescan the whole tail each
    // time.
    let cursor = 0;

    while (waiting.size) {
      let next = null;
      const near = radioMap.near[radioMap.at.get(here)] || [];

      for (let at = 0; at < near.length; at++) {
        const candidate = radioMap.keys[near[at]];
        if (waiting.has(candidate)) { next = candidate; break; }
      }

      if (next === null) {
        // Its eight are all behind us. Take the next one still
        // standing, in the order the listing already had — a walk that
        // ran out of near neighbours carries on rather than stopping.
        while (cursor < rest.length && !waiting.has(rest[cursor].key)) {
          cursor += 1;
        }
        if (cursor >= rest.length) break;
        next = rest[cursor].key;
      }

      walk.push(waiting.get(next));
      waiting.delete(next);
      here = next;
    }

    queue = head.concat(walk);

    // Not animated, and `playNext` just above has already animated the
    // one row that was asked for. What this changes is the order of
    // everything still to come — nine hundred rows crossing each other
    // says nothing anyone could follow, and measuring them all to work
    // out how costs two seconds, measured.
    justMoved = null;
    paint();
  }

  function chooseOrder(order) {
    const known = ["name", "shuffle", "radio"];
    playOrder = known.indexOf(order) === -1 ? "youtube" : order;
    showOrder();

    // Carried in the filter form, so a refetch for any other reason — a
    // filter, a save, a playlist change — brings the listing back in the
    // order that is playing rather than in the server's default.
    if (orderField) orderField.value = playOrder;

    // Where the walk begins: the song playing, so choosing the radio
    // carries on from what you are listening to rather than starting
    // the library again. Empty when nothing plays, which the server
    // reads as "from the top".
    const startField = document.getElementById("start-field");
    if (startField) {
      startField.value = playOrder === "radio" && queue[index]
        ? queue[index].key
        : "";
    }

    if (playOrder === "shuffle") {
      // No round trip: a random order is not the server's to hold, and
      // the rows to put in one are already here.
      const entries = queueFromRows();

      if (entries.length) setQueue(shuffled(entries), 0);
      return;
    }

    // Asked from the server, because by now the rows on screen are in
    // the queue's order rather than in the one being asked for.
    // Set before the request and read when the listing lands. Not
    // cleared from the promise htmx hands back: that resolves before the
    // settle, so it cleared the flag before the listing it was set for
    // had arrived — the switch changed while the queue went on playing
    // the order it was already in.
    orderAsked = true;
    window.htmx.ajax("GET", "/fragments/list", {
      target: "#list",
      swap: "innerHTML",
      source: document.getElementById("filters"),
    });
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

  // Ten seconds a face. Five read as restless on a line you are not
  // watching: the movement caught the eye more often than the second
  // face was worth.
  const BOARD_HOLD = 10000;

  // Bumped on every new face. A turn in flight checks it before touching
  // a slot, so a song changed mid-flap does not finish spelling out the
  // previous one.
  let boardEra = 0;

  // The faces this board can show, in the order it shows them: the
  // release, the recording code, the playlist, then where the file came
  // from. Only the playlist is always there; a face with nothing to say
  // does not take a turn, which is why they are filtered rather than
  // padded — an empty one would cost ten seconds of nothing.
  function boardFaces(board) {
    return [
      board.dataset.release || "",
      board.dataset.recording || "",
      board.dataset.playlist || "",
      board.dataset.origin || ""
    ].filter(function (face) { return face !== ""; });
  }

  // How many characters the line can hold at the point the board starts.
  //
  // Nothing bounds a face: a release line reached 144 characters and a
  // video title 126, against a panel that holds about sixty. Rendered
  // whole they ran out under the column beside them and gave the whole
  // page a horizontal scrollbar — measured at 1118 pixels of board
  // inside 469 pixels of line.
  //
  // Measured rather than assumed. The board is monospace, but its size
  // comes from an em-relative rule, so a character is only the width it
  // happens to be in this panel at this font size. The reading is taken
  // from the board's own left edge, so whatever shares the line before
  // it — the unsaved-edits notice — is already accounted for.
  function boardRoom(board) {
    const line = board.parentElement;

    if (!line) return 80;

    const probe = document.createElement("span");
    probe.className = "slot";
    probe.textContent = "0";
    board.appendChild(probe);
    const one = probe.getBoundingClientRect().width;
    probe.remove();

    if (!one) return 80;

    const room = line.getBoundingClientRect().right
      - board.getBoundingClientRect().left;

    return Math.max(8, Math.floor(room / one));
  }

  // A face cut to the room there is, with an ellipsis standing where the
  // rest was. One character of the budget goes to saying so.
  function fit(face, width) {
    return face.length <= width ? face : face.slice(0, width - 1) + "…";
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
    const width = Math.min(
      boardRoom(board),
      Math.max(...boardFaces(board).map(function (face) {
        return face.length;
      }))
    );
    text = fit(text, width);
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
    document.querySelectorAll(".board").forEach(function (board) {
      const faces = boardFaces(board);

      if (faces.length < 2) return;

      const next = ((parseInt(board.dataset.face, 10) || 0) + 1) % faces.length;
      board.dataset.face = String(next);
      showFace(board, faces[next], true);
    });
  }

  let boardClock = 0;

  // Restarted rather than left running: a song clicked one second before
  // the tick would otherwise show its playlist for one second and then
  // flip, which reads as a glitch rather than as a cycle.
  function restartBoards() {
    if (boardClock) window.clearInterval(boardClock);
    boardClock = 0;

    let turning = false;

    document.querySelectorAll(".board").forEach(function (board) {
      board.dataset.face = "0";
      showFace(board, boardFaces(board)[0] || "", false);
      turning = turning || boardFaces(board).length > 1;
    });

    if (turning) {
      boardClock = window.setInterval(turnBoards, BOARD_HOLD);
    }
  }

  // A request that failed swapped nothing, so the flag would have stood
  // for the next listing arriving for any other reason to claim — and a
  // filter keystroke would have restarted the queue.
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.detail && event.detail.successful === false) orderAsked = false;
  });

  // A listing asked for in a new order arrives here; it is the queue
  // now, and the run starts at the top — which is what choosing an order
  // means, and what the two buttons it replaced both did.
  //
  // Guarded by the flag rather than by "is something playing": a filter
  // keystroke swaps this same listing, and adopting that one would
  // restart the music at whoever was typing.
  //
  // At the swap and not at the settle, because this reads the order the
  // rows arrived in. Between those two moments the repaint runs and lays
  // the listing out in the queue's order — the one being replaced — so
  // by settle time the arriving order is gone, and the switch would have
  // chosen the order that was already playing.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "list") return;

    // Whatever brought this listing: the table belongs to it, and a
    // stale one would replan a walk over songs that are no longer here.
    readRadioMap();

    if (!orderAsked) return;
    orderAsked = false;

    const entries = queueFromRows();
    if (entries.length) setQueue(entries, 0);
  });

  restartBoards();
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.querySelector
        && event.target.querySelector(".board")) {
      restartBoards();
    }
    // The card is swapped in after the refresh that wrote the counter,
    // so every fresh one arrived empty and the run never said where it
    // was. Nothing has changed but the card — same queue, same cursor —
    // so the number is copied rather than worked out again.
    if (event.target && event.target.querySelector
        && event.target.querySelector("#workbench-position")) {
      showPosition();
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
    if (!following || following.key === queue[index].key) return;

    window.fetch("/songs/" + following.key + "/peaks").catch(function () {
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

    const orderButton = event.target.closest("[data-play-order]");
    if (orderButton) {
      chooseOrder(orderButton.dataset.playOrder);
      return;
    }

    // Only the workbench is left here: Play all and Shuffle were each a
    // way of building a queue, and the listing being the play order,
    // what they chose was an order. They are two of the three above.
    const queueButton = event.target.closest("[data-queue-action]");
    if (queueButton) {
      const entries = queueFromRows();
      if (!entries.length) return;

      document.body.classList.add("workbench-mode");
      setQueue(entries, 0);
      return;
    }

    if (event.target.closest('[data-workbench="exit"]')) {
      leaveWorkbench();
      return;
    }

    const playerButton = event.target.closest("[data-player-action]");
    if (playerButton) {
      const action = playerButton.dataset.playerAction;
      if (action === "next") move(1, true);
      else if (action === "previous") move(-1, true);
      else if (action === "toggle") {
        if (!queue.length) {
          const entries = queueFromRows();
          if (entries.length) setQueue(entries, 0);
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
      const shown = document.querySelector("#inspector [data-song-key]");
      if (!shown) return;

      const wanted = shown.dataset.songKey;
      const entries = queueFromRows();
      const at = entries.findIndex(function (entry) {
        return entry.key === wanted;
      });

      if (at >= 0) {
        // In the listing: select it there, exactly as clicking its row
        // would, so the queue and what you can see stay the same thing.
        setQueue(entries, at);
      } else {
        // Filtered out of the listing, or imported into a view that does
        // not show it. Play it on its own rather than refuse: you asked
        // for this song, and the alternative is a button that sometimes
        // does nothing.
        setQueue(
          [{
            // The key is what plays it; the video id is what the "watch
            // on YouTube" key opens, and the panel carries both.
            key: wanted,
            id: shown.dataset.songId || "",
            label: shown.dataset.label || "",
            duration: "",
            junk: false,
          }],
          0
        );
      }
      return;
    }

    // An imported song opens in the inspector. Only the rows that
    // finished carry an id: nothing reached the disk for the others, so
    // there is nothing to open, and a row that answers a click by doing
    // nothing is worse than one that plainly does not.
    const imported = event.target.closest(".import-row[data-song-key]");
    if (imported && !event.target.closest("button, a, input, label")) {
      // Staying put. The inspector sits above the tabs and is visible
      // from either of them, so switching would take you away from the
      // list you are reading to show you something you could already
      // see — and lose your place in a run of thirty rows.
      inspect(imported.dataset.songKey);
      return;
    }

    const lineUp = event.target.closest("[data-play-next]");
    if (lineUp) {
      // Whatever carries the key: a row of the listing, or an entry in
      // the neighbours panel. One button, one meaning, two places — a
      // second handler for the panel would be a second chance for the
      // two to disagree about what lining a song up does.
      const holder = lineUp.closest("[data-song-key]");

      if (holder) lineUpOrTakeOut(holder.dataset.songKey);
      return;
    }

    // And the whole neighbour row does what its button does. The same
    // rule the listing follows — a click anywhere on a row acts on that
    // row — so the button is where the two states are *said*, not the
    // only place they can be reached.
    // The row already next is not one of them: it is where the walk was
    // going anyway, so there is nothing for a click to ask for.
    const near = event.target.closest("#neighbours .neighbour:not(.is-next)");
    if (near && !event.target.closest("button, a")) {
      lineUpOrTakeOut(near.dataset.songKey);
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
          return entry.key === row.dataset.songKey;
        })
      );
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.target.matches("input, textarea, select")) return;

    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        move(1, true);
        break;
      case "ArrowLeft":
        event.preventDefault();
        move(-1, true);
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

  // Unsaved work, in one place. Two things follow from it: the panel
  // stops following the player, and Save becomes available. They were
  // one flag and one side effect before; now the side effect is written
  // down, because a second caller was about to forget it.
  // Nothing left to hold: the flag and the sign it puts on the panel.
  function forgetEdits() {
    dirty = false;

    const panel = document.getElementById("inspector");
    if (!panel) return;

    panel.classList.remove("holding-edits");
    panel.classList.remove("editing");
  }

  // What the file holds, as the server rendered it: an input's
  // defaultValue is its `value` attribute. So the clean state travels
  // with the panel and nothing is kept on the side — a copy would go
  // stale the moment htmx swapped the panel for another song.
  function editedFields() {
    const form = document.querySelector("#inspector form");
    if (!form) return [];

    return [...form.querySelectorAll("input")].filter(function (field) {
      return field.value !== field.defaultValue;
    });
  }

  // Read each time, never latched. It used to be a flag that only went
  // one way: typing a character and deleting it again left the panel
  // claiming it held unsaved work — Save enabled, the player no longer
  // followed — until the panel was replaced. Comparing against what
  // the file holds costs three string comparisons and is simply true.
  function rereadEdits() {
    const changed = editedFields().length > 0;
    const panel = document.getElementById("inspector");

    // Showing what has changed, and only on the way in. This is the one
    // place both ways of changing a field arrive — typing, and taking
    // Shazam's answer — so it is the one place that has to reveal the
    // fields when the panel is showing the neighbours instead: a form
    // filled behind a face nobody is looking at is a trap. On the way
    // out it leaves the face alone, because snatching it back the
    // moment the last character is deleted is its own kind of trap.
    if (changed && !dirty) showPanelFace("edit");

    dirty = changed;

    if (panel) {
      panel.classList.toggle("editing", changed);
      // Nothing differs, so nothing is being held: the panel may follow
      // the player again.
      if (!changed) panel.classList.remove("holding-edits");
    }

    const save = document.querySelector(
      "#inspector form button[type='submit']"
    );

    if (save) save.disabled = !changed;
  }

  // Cancel. The values the server rendered are still in the markup, so
  // putting them back fetches nothing and cannot be out of date.
  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-undo-edits]")) return;

    const form = document.querySelector("#inspector form");
    if (!form) return;

    form.querySelectorAll("input").forEach(function (field) {
      field.value = field.defaultValue;
    });

    rereadEdits();
  });

  // Anything typed in the inspector is unsaved work; stop following the
  // player until it is saved or the panel is replaced.
  document.addEventListener("input", function (event) {
    if (event.target.closest("#inspector")) rereadEdits();
  });

  // Both ways out of the Shazam block give the fields back. Dismissing
  // empties it, which is also what stops it polling: the attributes that
  // drive the poll go with the markup.
  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-shazam-dismiss]")) return;

    const block = document.querySelector("#inspector #shazam");
    if (!block) return;

    block.classList.remove("showing");
    block.innerHTML = "";
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id !== "inspector") return;

    // A fresh panel carries no unsaved edits, and nothing left to hold.
    forgetEdits();
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
    rereadEdits();

    // And the block goes, because the fields it was covering are the
    // ones that just changed — leaving it up would hide the only
    // evidence that anything happened.
    const block = document.querySelector("#inspector #shazam");

    if (block) {
      block.classList.remove("showing");
      block.innerHTML = "";
    }
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

    // Through `move`, which lets go of the edits itself — this path
    // used to clear the flag on its own and leave the sign it puts on
    // the panel standing.
    move(1, true);
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

  // The observer above watches for rows arriving and leaving, and it
  // fires as a microtask straight after the swap — before htmx has
  // settled the attributes it kept from the rows that were there. The
  // settle then wrote the new markup's `class` over everything painted
  // in between, which is how a filter keystroke put out the light on the
  // song still playing. Painting again once the attributes are final is
  // the whole of the fix; a paint over an already-right listing writes
  // nothing.
  document.body.addEventListener("htmx:afterSettle", function (event) {
    if (event.target.id === "list") paint();
  });

  paint();

  // Arriving, the panel described nothing: "Select a song." The first
  // row is the obvious one to describe, so it describes that — and
  // describing a song is not playing it. The player stays silent until
  // asked, and the panel's own Play this button is what asks.
  //
  // Guarded, though nothing reaches it today: the console route sends
  // "Select a song." every time, `&song=` in the address included, so the
  // panel is always empty on arrival. Both cases this once named — a
  // reload during playback, a bookmarked song — would need a server that
  // pre-fills the panel, and there is none.
  //
  // Kept rather than dropped, because that is a template's behaviour and
  // not this function's: the day the shell ships a song, this check is
  // what stops the first row from overwriting it.
  if (!document.querySelector("#inspector [data-song-key]")) {
    const first = rows()[0];
    if (first) inspect(first.dataset.songKey);
  }
})();
