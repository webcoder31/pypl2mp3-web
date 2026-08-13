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

  function play(i) {
    if (!queue.length) return;

    // Wrap rather than stop, the way the CLI's play loops its selection.
    index = (i + queue.length) % queue.length;
    audio.src = "/songs/" + queue[index] + "/audio";
    paint();

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

  const list = document.getElementById("list");
  if (list) observer.observe(list, { childList: true, subtree: true });

  paint();
})();
