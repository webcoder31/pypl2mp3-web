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

  document.addEventListener("click", function (event) {
    const tab = event.target.closest("#tabs [data-tab]");
    if (tab) {
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
  const elapsed = document.getElementById("player-elapsed");
  const total = document.getElementById("player-total");
  const seek = document.getElementById("seek");
  const waveform = document.getElementById("waveform");
  const position = document.getElementById("player-position");
  const toggle = document.querySelector('[data-player-action="toggle"]');
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

    if (!current) {
      bar.classList.add("idle");
      if (toolbar) toolbar.classList.add("idle");
      nextKey.textContent = "NEXT";
      nextText.textContent = "Nothing playing";
      upNext.title = "";
      // The count the toolbar used to render server-side. It is the
      // same number the position turns into once something plays, so
      // nothing is lost by letting one slot carry both.
      const total = rows().length;
      position.textContent = total ? total + " songs" : "";
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
    nextText.textContent = following
      ? following.duration + "  " + following.label +
        (following.junk ? " (JUNK)" : "")
      : "";
    upNext.title = nextKey.textContent + " " + nextText.textContent;
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

  function inspect(id) {
    if (dirty) return;

    const shown = document.querySelector("#inspector [data-song-id]");
    if (shown && shown.dataset.songId === id) return;

    const panel = inWorkbench() ? "/fragments/workbench/" : "/fragments/inspector/";
    window.htmx.ajax("GET", panel + id, "#inspector");
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
  // The waveform
  //
  // Peaks come from the server, which computes them once per song and
  // keeps them in the MP3's tags. They are decoration over a control
  // that already works: nothing below touches how #seek is operated,
  // and a song whose peaks never arrive keeps the plain bar.
  // ---------------------------------------------------------------

  const brush = waveform.getContext("2d");
  let peaks = null;

  // Skipping through a playlist leaves slower requests in flight behind
  // faster ones. Without this, the waveform you end up looking at is
  // whichever response happened to land last, not the song playing.
  let wanted = 0;

  function loadWaveform(id) {
    const mine = ++wanted;

    peaks = null;
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
      })
      .catch(function () {
        // Offline, aborted, malformed: the plain bar is already there.
      });
  }

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
    const edge = Math.round(done * peaks.length);

    const slot = width / peaks.length;
    // One device-independent pixel of air between bars, and never less
    // than one device pixel of bar.
    const bar = Math.max(1, slot - dpr);

    brush.clearRect(0, 0, width, height);

    function paintBars(from, to, colour) {
      brush.fillStyle = colour;
      for (let i = from; i < to; i++) {
        // Silence still draws a hairline: the bar is the control, and a
        // gap in it would read as a gap in the song.
        const tall = Math.max(dpr, peaks[i] * height);
        brush.fillRect(i * slot, (height - tall) / 2, bar, tall);
      }
    }

    paintBars(0, edge, played);
    paintBars(edge, peaks.length, rest);
  }

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
  document.addEventListener("change", function (event) {
    if (event.target.id !== "pick-all") return;

    document
      .querySelectorAll('#import-form input[name="songs"]')
      .forEach(function (box) {
        box.checked = event.target.checked;
      });
  });

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
      return;
    }

    // An imported song opens in the inspector. Only the rows that
    // finished carry an id: nothing reached the disk for the others, so
    // there is nothing to open, and a row that answers a click by doing
    // nothing is worse than one that plainly does not.
    const imported = event.target.closest(".import-row[data-song-id]");
    if (imported && !event.target.closest("button, a, input, label")) {
      showTab("playlist");
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
    if (event.target.id === "inspector") dirty = false;
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
})();
