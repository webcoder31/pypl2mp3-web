// The console's persistent player and selection.
//
// The queue is not a separate data structure: it is read out of the rows
// currently in #list. One source of truth, so the visible list and the
// thing being played can never disagree about what track 12 is.
//
// Playback state lives here and only here. #player sits outside every
// htmx target, so swapping the list, the nav or the inspector leaves the
// <audio> element — and the sound — untouched.

(function () {
  "use strict";

  const audio = document.getElementById("audio");
  const bar = document.getElementById("player");
  const label = document.getElementById("player-label");
  const position = document.getElementById("player-position");
  const videoLink = document.getElementById("player-video");
  const toggle = document.querySelector('[data-player-action="toggle"]');
  const filters = document.getElementById("filters");
  const playlistField = document.getElementById("playlist-field");

  // Ids, in play order. Rebuilt from the DOM whenever the queue is set.
  let queue = [];
  let index = -1;

  function rows() {
    return Array.from(document.querySelectorAll("#list tr[data-song-id]"));
  }

  function rowFor(id) {
    return document.querySelector('#list tr[data-song-id="' + id + '"]');
  }

  function labelFor(id) {
    const row = rowFor(id);
    return row ? row.dataset.label : id;
  }

  function paint() {
    const current = queue[index];

    rows().forEach(function (row) {
      row.classList.toggle("playing", row.dataset.songId === current);
    });

    if (!current) {
      bar.classList.add("idle");
      label.textContent = "Nothing playing";
      position.textContent = "";
      return;
    }

    bar.classList.remove("idle");
    label.textContent = labelFor(current);
    label.title = label.textContent;
    position.textContent = index + 1 + " / " + queue.length;
    videoLink.href = "https://youtu.be/" + current;
  }

  // Set when the inspector's form has edits nobody has saved. The panel
  // follows the playing song, and a track ending mid-sentence must not
  // wipe what you were typing.
  let dirty = false;

  function inspect(id) {
    if (dirty) return;

    const shown = document.querySelector("#inspector [data-song-id]");
    if (shown && shown.dataset.songId === id) return;

    window.htmx.ajax("GET", "/fragments/inspector/" + id, "#inspector");
  }

  function play(i) {
    if (!queue.length) return;

    // Wrap rather than stop, the way the CLI's play loops its selection.
    index = (i + queue.length) % queue.length;
    audio.src = "/songs/" + queue[index] + "/audio";
    paint();

    // The song being judged is the song being heard: one cursor, not two.
    inspect(queue[index]);

    audio.play().catch(function () {
      // Browsers refuse autoplay until the page has been interacted
      // with. Not an error — the controls are right there.
    });
  }

  function move(step) {
    if (queue.length) play(index + step);
  }

  // Setting the queue: the visible listing becomes what plays, which is
  // what every music player does when you start a track from a view.
  function setQueue(ids, startAt) {
    queue = ids;
    play(startAt || 0);
  }

  function shuffled(ids) {
    const out = ids.slice();
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  }

  audio.addEventListener("ended", function () {
    move(1);
  });

  audio.addEventListener("play", function () {
    toggle.textContent = "⏸";
  });

  audio.addEventListener("pause", function () {
    toggle.textContent = "▶";
  });

  // Playing a song that then leaves the listing (filtered out, junkized)
  // would otherwise show a stale row highlight and a raw id as a label.
  const observer = new MutationObserver(paint);

  // Delegated: #list and #nav are replaced wholesale by htmx, so nothing
  // may hold a listener on an element inside them.
  document.addEventListener("click", function (event) {
    const navButton = event.target.closest("#nav button[data-playlist]");
    if (navButton) {
      playlistField.value = navButton.dataset.playlist;
      filters.requestSubmit();
      return;
    }

    const queueButton = event.target.closest("[data-queue-action]");
    if (queueButton) {
      const ids = rows().map(function (row) {
        return row.dataset.songId;
      });
      if (!ids.length) return;
      setQueue(
        queueButton.dataset.queueAction === "shuffle" ? shuffled(ids) : ids
      );
      return;
    }

    const playerButton = event.target.closest("[data-player-action]");
    if (playerButton) {
      const action = playerButton.dataset.playerAction;
      if (action === "next") move(1);
      else if (action === "previous") move(-1);
      else if (action === "toggle") {
        if (!queue.length) {
          const ids = rows().map(function (row) {
            return row.dataset.songId;
          });
          if (ids.length) setQueue(ids);
        } else if (audio.paused) {
          audio.play();
        } else {
          audio.pause();
        }
      }
      return;
    }

    // A click anywhere else on a row plays it, taking the listing as the
    // queue. Buttons and links inside the row keep their own meaning.
    const row = event.target.closest("#list tr[data-song-id]");
    if (row && !event.target.closest("button, a")) {
      const ids = rows().map(function (r) {
        return r.dataset.songId;
      });
      setQueue(ids, ids.indexOf(row.dataset.songId));
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
          window.open(videoLink.href, "_blank", "noopener");
        }
        break;
    }
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
