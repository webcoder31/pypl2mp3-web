// Queue player for a selection of songs.
//
// Mirrors the CLI's `play`: right and left move through the queue, space
// pauses, tab opens the video, escape leaves. The CLI drives pygame from
// sshkeyboard; here the browser owns playback and this only sequences it.
//
// No framework: one audio element, an array, and a handful of listeners.

(function () {
  "use strict";

  const data = document.getElementById("queue-data");
  if (!data) return;

  const queue = JSON.parse(data.textContent);
  if (!queue.length) return;

  const audio = document.getElementById("player-audio");
  const cover = document.getElementById("player-cover");
  const label = document.getElementById("player-label");
  const position = document.getElementById("player-position");
  const videoLink = document.getElementById("player-video");
  const list = document.getElementById("queue-list");

  let index = 0;

  function show(i) {
    // Wrap rather than stop: the CLI loops through its selection too.
    index = (i + queue.length) % queue.length;
    const song = queue[index];

    audio.src = "/songs/" + song.youtube_id + "/audio";
    cover.src = "/songs/" + song.youtube_id + "/cover";
    cover.style.display = "";
    label.textContent = song.label;
    position.textContent = index + 1 + " / " + queue.length;
    videoLink.href = "https://youtu.be/" + song.youtube_id;

    if (list) {
      Array.prototype.forEach.call(list.children, function (row, i) {
        row.classList.toggle("playing", i === index);
      });
      const active = list.children[index];
      if (active && active.scrollIntoView) {
        active.scrollIntoView({ block: "nearest" });
      }
    }

    audio.play().catch(function () {
      // Autoplay can be refused until the page has been interacted with.
      // Not an error: the controls are right there.
    });
  }

  function move(step) {
    show(index + step);
  }

  audio.addEventListener("ended", function () {
    move(1);
  });

  cover.addEventListener("error", function () {
    // Songs without embedded art 404 here; hide rather than show a broken
    // image icon.
    cover.style.display = "none";
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
      case "Spacebar":
        event.preventDefault();
        if (audio.paused) {
          audio.play();
        } else {
          audio.pause();
        }
        break;
      case "Tab":
        event.preventDefault();
        window.open(videoLink.href, "_blank", "noopener");
        break;
      case "Escape":
        event.preventDefault();
        window.location.href = data.dataset.exit || "/";
        break;
    }
  });

  document.querySelectorAll("[data-player-action]").forEach(function (button) {
    button.addEventListener("click", function () {
      const action = button.dataset.playerAction;
      if (action === "next") move(1);
      else if (action === "previous") move(-1);
      else if (action === "toggle") {
        if (audio.paused) audio.play();
        else audio.pause();
      }
    });
  });

  if (list) {
    Array.prototype.forEach.call(list.children, function (row, i) {
      row.addEventListener("click", function () {
        show(i);
      });
    });
  }

  show(0);
})();
