/* 记忆星图：主题分区布局 + 画布渲染 + 缩放/平移/选中 */
(function () {
  "use strict";

  var TOKEN = new URLSearchParams(location.search).get("t") || "";

  var canvas = document.getElementById("map");
  var ctx = canvas.getContext("2d");
  var statsEl = document.getElementById("stats");
  var topicsEl = document.getElementById("topics");
  var detailEl = document.getElementById("detail");

  var nodes = [];
  var links = [];
  var topicOrder = [];
  var view = { x: 0, y: 0, k: 1 };
  var hovered = null;
  var pinned = null;
  var highlightTopic = null;
  var drag = null;
  var dpr = 1;

  function colorFor(topic) {
    var h = 0;
    for (var i = 0; i < topic.length; i++) h = (h * 33 + topic.charCodeAt(i)) % 360;
    return "hsl(" + h + ", 62%, 62%)";
  }

  // 每个主题一个扇区，扇区大小按条目数分配；节点在扇区内由内向外旋出
  function layout() {
    var groups = {};
    nodes.forEach(function (n) {
      var t = n.topic || "其他";
      (groups[t] = groups[t] || []).push(n);
    });
    topicOrder = Object.keys(groups).sort(function (a, b) {
      return groups[b].length - groups[a].length;
    });

    var GAP = 0.07;
    var usable = Math.PI * 2 - GAP * Math.max(1, topicOrder.length);
    var weight = nodes.length || 1;
    var cursor = -Math.PI / 2;

    topicOrder.forEach(function (topic) {
      var list = groups[topic].slice().sort(function (a, b) {
        return String(a.t || "").localeCompare(String(b.t || ""));
      });
      var span = usable * (list.length / weight);
      var mid = cursor + span / 2;
      cursor += span + GAP;

      list.forEach(function (n, i) {
        var frac = list.length === 1 ? 0.5 : i / (list.length - 1);
        var angle = cursor - GAP - span + span * (0.12 + 0.76 * frac);
        var radius = 90 + 250 * Math.sqrt((i + 1) / list.length);
        n._a = angle;
        n._r = radius;
        n._x = Math.cos(angle) * radius;
        n._y = Math.sin(angle) * radius;
        n._color = colorFor(topic);
        n._mid = mid;
      });
    });
  }

  function fit() {
    if (!nodes.length) { view = { x: 0, y: 0, k: 1 }; return; }
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      minX = Math.min(minX, n._x); maxX = Math.max(maxX, n._x);
      minY = Math.min(minY, n._y); maxY = Math.max(maxY, n._y);
    });
    var pad = 70;
    var w = Math.max(1, innerWidth - pad * 2);
    var h = Math.max(1, innerHeight - pad * 2);
    var k = Math.min(w / Math.max(1, maxX - minX), h / Math.max(1, maxY - minY), 1.8);
    view.k = k;
    view.x = -(minX + maxX) / 2;
    view.y = -(minY + maxY) / 2;
  }

  function screenOf(n) {
    return {
      x: (n._x + view.x) * view.k + innerWidth / 2,
      y: (n._y + view.y) * view.k + innerHeight / 2
    };
  }

  function resize() {
    dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.floor(innerWidth * dpr);
    canvas.height = Math.floor(innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function hinted(n) {
    var topic = n.topic || "其他";
    if (highlightTopic && topic !== highlightTopic) return false;
    return true;
  }

  function draw() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);

    var active = pinned || hovered;

    links.forEach(function (l) {
      var a = l._a, b = l._b;
      if (!a || !b) return;
      var sa = screenOf(a), sb = screenOf(b);
      var on = active && (active.id === a.id || active.id === b.id);
      ctx.strokeStyle = on ? "rgba(150, 205, 235, .55)" : "rgba(110, 150, 180, .18)";
      ctx.lineWidth = on ? 1.6 : 1;
      ctx.beginPath();
      ctx.moveTo(sa.x, sa.y);
      var cx = (sa.x + sb.x) / 2 + (sb.y - sa.y) * 0.12;
      var cy = (sa.y + sb.y) / 2 - (sb.x - sa.x) * 0.12;
      ctx.quadraticCurveTo(cx, cy, sb.x, sb.y);
      ctx.stroke();
    });

    nodes.forEach(function (n) {
      if (!hinted(n)) return;
      var p = screenOf(n);
      var r = Math.max(1.6, (1.8 + (n.importance || 0) * 5) * view.k);
      var glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 3);
      glow.addColorStop(0, n._color.replace("hsl", "hsla").replace(")", ", .35)"));
      glow.addColorStop(1, "hsla(0, 0%, 0%, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r * 3, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = n._color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();

      if (active && active.id === n.id) {
        ctx.strokeStyle = "#f2f8ff";
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r + 3.5, 0, Math.PI * 2);
        ctx.stroke();
      }
    });
  }

  function hitTest(x, y) {
    var best = null, bestD = 14;
    for (var i = nodes.length - 1; i >= 0; i--) {
      var n = nodes[i];
      if (!hinted(n)) continue;
      var p = screenOf(n);
      var d = Math.hypot(x - p.x, y - p.y);
      if (d < bestD) { bestD = d; best = n; }
    }
    return best;
  }

  function showDetail(n) {
    detailEl.textContent = "";
    var body = document.createElement("div");
    body.className = "body";
    body.textContent = n.summary;
    var meta = document.createElement("div");
    meta.className = "meta";
    var pct = Math.round((n.importance || 0) * 100);
    meta.textContent = (n.topic || "其他") + " · 重要度 " + pct + "%" +
      (n.t ? " · " + n.t : "");
    detailEl.appendChild(body);
    detailEl.appendChild(meta);
    detailEl.hidden = false;
  }

  function renderTopics() {
    topicsEl.textContent = "";
    topicOrder.forEach(function (topic) {
      var count = nodes.filter(function (n) { return (n.topic || "其他") === topic; }).length;
      var row = document.createElement("div");
      row.className = "row";
      var swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = colorFor(topic);
      var name = document.createElement("span");
      name.className = "name";
      name.textContent = topic;
      var num = document.createElement("span");
      num.className = "num";
      num.textContent = count;
      row.appendChild(swatch);
      row.appendChild(name);
      row.appendChild(num);
      row.title = "只看这个主题";
      row.addEventListener("click", function () {
        highlightTopic = highlightTopic === topic ? null : topic;
        pinned = null;
        detailEl.hidden = true;
        draw();
      });
      topicsEl.appendChild(row);
    });
  }

  function start() {
    fetch("/api/memories", { headers: { "X-Gate-Token": TOKEN } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        nodes = data.nodes || [];
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        links = (data.links || []).map(function (l) {
          return { _a: byId[l.source], _b: byId[l.target] };
        });
        var src = data.source || {};
        if (src.error) {
          statsEl.textContent = "库不可用：" + src.error;
        } else {
          statsEl.textContent = nodes.length + " 条记忆 · " + links.length + " 条关联";
        }
        layout();
        fit();
        renderTopics();
        draw();
      })
      .catch(function (err) {
        statsEl.textContent = "加载失败：" + err.message;
      });
  }

  canvas.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var factor = Math.exp(-ev.deltaY * 0.0012);
    var k2 = Math.min(6, Math.max(0.15, view.k * factor));
    var mx = ev.clientX - innerWidth / 2;
    var my = ev.clientY - innerHeight / 2;
    view.x += mx / view.k - mx / k2;
    view.y += my / view.k - my / k2;
    view.k = k2;
    draw();
  }, { passive: false });

  canvas.addEventListener("pointerdown", function (ev) {
    drag = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y, moved: false };
    canvas.classList.add("grabbing");
    canvas.setPointerCapture(ev.pointerId);
  });

  canvas.addEventListener("pointermove", function (ev) {
    if (drag) {
      var dx = ev.clientX - drag.x;
      var dy = ev.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.moved) {
        view.x = drag.vx + dx / view.k;
        view.y = drag.vy + dy / view.k;
        draw();
      }
      return;
    }
    var n = hitTest(ev.clientX, ev.clientY);
    if (n !== hovered) {
      hovered = n;
      draw();
    }
    if (n && !pinned) showDetail(n);
    if (!n && !pinned) detailEl.hidden = true;
  });

  canvas.addEventListener("pointerup", function (ev) {
    canvas.classList.remove("grabbing");
    var wasDrag = drag && drag.moved;
    drag = null;
    canvas.releasePointerCapture(ev.pointerId);
    if (wasDrag) return;
    var n = hitTest(ev.clientX, ev.clientY);
    if (n) {
      pinned = n;
      showDetail(n);
    } else {
      pinned = null;
      detailEl.hidden = true;
    }
    draw();
  });

  canvas.addEventListener("dblclick", function () {
    pinned = null;
    highlightTopic = null;
    detailEl.hidden = true;
    fit();
    draw();
  });

  addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      pinned = null;
      highlightTopic = null;
      detailEl.hidden = true;
      draw();
    }
  });

  addEventListener("resize", resize);
  resize();
  start();
})();
