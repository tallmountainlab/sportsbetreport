// "My team": re-colors the paper in the reader's team colors and pulls that
// team's games, line moves and highlights to the top. Saved on this device only.
(function () {
  var KEY = "sbr-team";
  var root = document.documentElement;
  var teams = [], videos = [];

  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\./g, "").toLowerCase().trim();
  }
  function isTeam(name, t) {
    var n = norm(name);
    return n === norm(t.name) || n === norm(t.nick) || n.slice(-(norm(t.nick).length + 1)) === " " + norm(t.nick);
  }
  function hex(c) { c = c.replace("#", ""); return [0, 2, 4].map(function (i) { return parseInt(c.substr(i, 2), 16) / 255; }); }
  function lum(c) {
    var v = hex(c).map(function (x) { return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function rgbToHex(s) {
    var m = (s || "").match(/\d+/g); if (!m) return s.trim();
    return "#" + m.slice(0, 3).map(function (n) { return ("0" + (+n).toString(16)).slice(-2); }).join("");
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  function store(id) { try { id ? localStorage.setItem(KEY, id) : localStorage.removeItem(KEY); } catch (e) {} }
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }

  function colors(t) {
    var paper = rgbToHex(getComputedStyle(document.body).backgroundColor);
    var accent = [t.primary, t.secondary].filter(function (c) { return contrast(c, paper) >= 3; })[0] || "";
    var ink = contrast(t.primary, "#ffffff") >= contrast(t.primary, "#000000") ? "#ffffff" : "#000000";
    var s = root.style;
    s.setProperty("--team", t.primary);
    s.setProperty("--team2", t.secondary);
    s.setProperty("--team-ink", ink);
    accent ? s.setProperty("--accent", accent) : s.removeProperty("--accent");
  }
  function clearColors() {
    ["--team", "--team2", "--team-ink", "--accent"].forEach(function (p) { root.style.removeProperty(p); });
  }

  function videoCard(v) {
    return '<a class="vid" href="https://www.youtube.com/watch?v=' + esc(v.id) + '" target="_blank" rel="noopener">' +
      '<span class="thumb"><img src="https://i.ytimg.com/vi/' + esc(v.id) + '/mqdefault.jpg" alt="" loading="lazy" width="320" height="180">' +
      '<span class="play" aria-hidden="true">&#9654;</span></span><span class="vt">' + esc(v.title) + "</span></a>";
  }

  function yourTeam(t) {
    var box = document.getElementById("yourteam");
    if (!box) return;
    document.querySelectorAll("tr.mine").forEach(function (r) { r.classList.remove("mine"); });
    if (!t) { box.hidden = true; box.innerHTML = ""; return; }
    var rows = [].slice.call(document.querySelectorAll('section.league tr[data-lg="' + t.league + '"]')).filter(function (r) {
      return isTeam(r.dataset.home, t) || isTeam(r.dataset.away, t);
    });
    var moves = [].slice.call(document.querySelectorAll('tr[data-lg="' + t.league + '"]')).filter(function (r) {
      return !r.closest("section.league") && !r.closest("#yourteam") && (isTeam(r.dataset.home, t) || isTeam(r.dataset.away, t));
    });
    rows.concat(moves).forEach(function (r) { r.classList.add("mine"); });
    var html = '<div class="yt-head"><span class="yt-pen">' + esc(t.nick) + "</span><h2>Your " + esc(t.nick) + "</h2></div>";
    if (rows.length) {
      var table = rows[0].closest("table").cloneNode(false);
      table.appendChild(rows[0].closest("table").tHead.cloneNode(true));
      var body = document.createElement("tbody");
      rows.forEach(function (r) { var c = r.cloneNode(true); c.classList.remove("mine"); body.appendChild(c); });
      table.appendChild(body);
      html += '<div class="tbl">' + table.outerHTML + "</div>";
    } else if (document.querySelector("section.league")) {
      html += '<p class="muted">The ' + esc(t.nick) + " aren't on the board in the next day and a half. Check back tomorrow morning.</p>";
    } else {
      html += '<p class="muted">Today\'s full report has every ' + esc(t.league_name) + ' game, with yours pulled to the top. ' +
        '<a href="/reports/">Open the latest report</a>.</p>';
    }
    if (moves.length) html += '<p class="small">The ' + esc(t.nick) + " are also in today's big movers below.</p>";
    var mine = videos.filter(function (v) { return v.league === t.league && norm(v.title).indexOf(norm(t.nick)) > -1; }).slice(0, 4);
    if (mine.length) html += '<h3>' + esc(t.nick) + ' highlights</h3><div class="vids row4">' + mine.map(videoCard).join("") + "</div>";
    box.innerHTML = html;
    box.hidden = false;
  }

  function apply(id) {
    var t = teams.filter(function (x) { return x.id === id; })[0];
    var label = document.getElementById("myteam-label");
    var pen = document.getElementById("pennant");
    if (t) {
      root.dataset.team = t.id;
      colors(t);
      if (label) label.textContent = "My team: " + t.nick;
      if (pen) { pen.textContent = t.name; pen.hidden = false; }
    } else {
      delete root.dataset.team;
      clearColors();
      if (label) label.textContent = "Pick your team";
      if (pen) pen.hidden = true;
    }
    document.querySelectorAll(".picker button[data-team]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.team === (t && t.id) ? "true" : "false");
    });
    yourTeam(t);
  }

  document.addEventListener("click", function (ev) {
    var b = ev.target.closest(".picker button[data-team]");
    if (!b) return;
    store(b.dataset.team);
    apply(b.dataset.team);
    var d = b.closest("details"); if (d) d.open = false;
  });

  Promise.all([
    fetch("/teams.json").then(function (r) { return r.json(); }),
    fetch("/highlights.json").then(function (r) { return r.json(); }).catch(function () { return { videos: [] }; })
  ]).then(function (res) {
    teams = res[0]; videos = res[1].videos || [];
    apply(saved());
  }).catch(function () {});
})();
