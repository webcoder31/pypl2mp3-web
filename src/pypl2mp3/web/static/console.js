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

  const audio = document.getElementById("audio");
  const bar = document.getElementById("player");
  const upNext = document.getElementById("player-next");
  const position = document.getElementById("player-position");
  const videoLink = document.getElementById("player-video");
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

    rows().forEach(function (row) {
      row.classList.toggle(
        "playing", current && row.dataset.songId === current.id
      );
    });

    if (!current) {
      bar.classList.add("idle");
      upNext.textContent = "Nothing playing";
      upNext.title = "";
      position.textContent = "";
      return;
    }

    bar.classList.remove("idle");
    position.textContent = index + 1 + " / " + queue.length;
    videoLink.href = "https://youtu.be/" + current.id;

    // What is playing is already the inspector's whole job. What the bar
    // can say that nothing else does is what comes next.
    const following =
      queue[(index + direction + queue.length) % queue.length];
    const arrow = direction < 0 ? "NEXT ←" : "NEXT →";
    upNext.textContent = following
      ? arrow +
        "  " +
        following.duration +
        "  " +
        following.label +
        (following.junk ? " (JUNK)" : "")
      : "";
    upNext.title = upNext.textContent;
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
    audio.src = "/songs/" + queue[index].id + "/audio";
    paint();

    // The song being judged is the song being heard: one cursor, not two.
    inspect(queue[index].id);

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
  function setQueue(entries, startAt) {
    queue = entries;
    // A fresh selection plays forward, whichever way the last one ended.
    direction = 1;
    // A findIndex that missed returns -1, which play() would wrap round
    // to the last track. Start at the top instead.
    play(startAt > 0 ? startAt : 0);
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
      setQueue(
        queueButton.dataset.queueAction === "shuffle"
          ? shuffled(entries)
          : entries
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
          const entries = queueFromRows();
          if (entries.length) setQueue(entries);
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
      const entries = queueFromRows();
      setQueue(
        entries,
        entries.findIndex(function (entry) {
          return entry.id === row.dataset.songId;
        })
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
