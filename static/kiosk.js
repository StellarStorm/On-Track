// Shared by the pages a kiosk screen shows (the board and the map).
// Kept to older JavaScript so the pages run on old iPads.

function getJSON(url, done, failed) {
  var request = new XMLHttpRequest();
  request.open("GET", url);
  request.timeout = 15000;
  request.onload = function () {
    var data = null;
    if (request.status === 200) {
      try {
        data = JSON.parse(request.responseText);
      } catch (error) {
        data = null;
      }
    }
    if (data) {
      done(data);
    } else {
      failed();
    }
  };
  request.onerror = failed;
  request.ontimeout = failed;
  request.send();
}

// The time of day as "9:05 PM", or "21:05" when timeFormat is "24".
function formatClock(date, timeFormat) {
  var hours = date.getHours();
  var minutes = ("0" + date.getMinutes()).slice(-2);
  if (timeFormat === "24") {
    return ("0" + hours).slice(-2) + ":" + minutes;
  }
  return (hours % 12 || 12) + ":" + minutes + (hours < 12 ? " AM" : " PM");
}

(function () {
  var RELOAD_HOURS = 6;
  var DISPLAY_CHECK_SECONDS = 5;
  var POINTER_IDLE_SECONDS = 3;

  // The control page can switch what this screen shows. Check every few
  // seconds, and reload when anything changes: the server then sends
  // whichever view is chosen, for the chosen station.
  var displayVersion = null;

  function watchDisplay() {
    function again() {
      setTimeout(watchDisplay, DISPLAY_CHECK_SECONDS * 1000);
    }
    getJSON(
      "/display",
      function (data) {
        if (displayVersion === null) {
          displayVersion = data.version;
        } else if (data.version !== displayVersion) {
          window.location.reload();
          return;
        }
        again();
      },
      again
    );
  }

  // Show the mouse pointer while it moves; hide it again when idle. The
  // page's CSS hides it unless the body has the "pointer" class.
  var pointerTimer = null;
  var pointerX = null;
  var pointerY = null;
  document.addEventListener("mousemove", function (event) {
    // Some browsers send mousemove when only the page changed.
    if (event.screenX === pointerX && event.screenY === pointerY) {
      return;
    }
    pointerX = event.screenX;
    pointerY = event.screenY;
    document.body.classList.add("pointer");
    clearTimeout(pointerTimer);
    pointerTimer = setTimeout(function () {
      document.body.classList.remove("pointer");
    }, POINTER_IDLE_SECONDS * 1000);
  });

  watchDisplay();
  // Old Safari slowly leaks memory on pages left open for days.
  setTimeout(function () {
    window.location.reload();
  }, RELOAD_HOURS * 3600 * 1000);
})();
