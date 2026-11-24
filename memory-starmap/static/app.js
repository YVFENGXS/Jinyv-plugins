/* 记忆星图：对数螺旋星系布局 + 深空配色 + 画布渲染 + 缩放/平移/选中 */
(function () {
  "use strict";

  var TOKEN = new URLSearchParams(location.search).get("t") || "";

  var canvas = document.getElementById("map");
  var ctx = canvas.getContext("2d");
  var statsEl = document.getElementById("stats");
  var topicsEl = document.getElementById("topics");
  var detailEl = document.getElementById("detail");

  var TAU = Math.PI * 2;

  /* 光谱色：低饱和、高亮度，像真实星等的恒星色，而不是随机色相 */
  var PALETTE = [
    [207, 58, 80],  // 星蓝
    [190, 50, 78],  // 青
    [258, 42, 82],  // 星紫
    [36, 60, 82],   // 暖金
    [342, 46, 82],  // 玫瑰
    [162, 36, 78],  // 薄荷
    [282, 36, 82],  // 紫罗兰
    [14, 54, 82]    // 琥珀
  ];

  function hueOf(c, a, dl) {
    var l = Math.max(0, Math.min(97, c[2] + (dl || 0)));
    if (a == null) return "hsl(" + c[0] + "," + c[1] + "%," + l + "%)";
    return "hsla(" + c[0] + "," + c[1] + "%," + l + "%," + a + ")";
  }

  var SPRITES = PALETTE.map(function (c) {
    var S = 64;
    var cv = document.createElement("canvas");
    cv.width = cv.height = S;
    var g = cv.getContext("2d");
    var grad = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    grad.addColorStop(0, "rgba(255,255,255,.92)");
    grad.addColorStop(0.14, hueOf(c, 0.9));
    grad.addColorStop(0.42, hueOf(c, 0.2));
    grad.addColorStop(1, hueOf(c, 0));
    g.fillStyle = grad;
    g.fillRect(0, 0, S, S);
    return cv;
  });

  var nodes = [];
  var links = [];
  var topicOrder = [];
  var topicColor = {};
  var view = { x: 0, y: 0, k: 1 };
  var hovered = null;
  var pinned = null;
  var highlightTopic = null;
  var drag = null;
  var dpr = 1;
  var bg = null;
  var bgR = 1;

  var MAX_R = 500;
  var ARMS = 2;
  var ARM_B = 0.5;

  /* 对数螺旋：r = a·e^(bθ)  =>  θ = ln(r/a)/b */
  function armTheta(r, arm) {
    return arm * (TAU / ARMS) + Math.log(Math.max(20, r) / 38) / ARM_B;
  }

  function rnd(seed) {
    var x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  function gauss(seed) {
    var u = Math.max(1e-6, rnd(seed));
    var v = rnd(seed + 17.31);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(TAU * v);
  }

  /* ---------- 布局：核球 + 两条对数螺旋臂，主题为大星团，长尾做臂间星野 ---------- */
  function layout() {
    var groups = {};
    nodes.forEach(function (n) {
      var t = n.topic || "其他";
      (groups[t] = groups[t] || []).push(n);
    });
    topicOrder = Object.keys(groups).sort(function (a, b) {
      return groups[b].length - groups[a].length;
    });

    topicColor = {};
    topicOrder.forEach(function (t, i) {
      topicColor[t] = PALETTE[i % PALETTE.length];
    });

    var rank = {};
    topicOrder.forEach(function (t, i) { rank[t] = i; });

    // 核球：最重要的一批记忆聚成明亮核心
    var byImp = nodes.slice().sort(function (a, b) {
      return (b.importance || 0) - (a.importance || 0);
    });
    var bulgeCount = Math.min(110, Math.round(nodes.length * 0.055));

    byImp.slice(0, bulgeCount).forEach(function (n, i) {
      var topic = n.topic || "其他";
      var ang = rnd(i * 3.71 + 1.7) * TAU;
      var rad = Math.abs(gauss(i * 5.13 + 2.9)) * 30 + 4;
      n._x = Math.cos(ang) * rad;
      n._y = Math.sin(ang) * rad * 0.9;
      n._ci = (rank[topic] || 0) % PALETTE.length;
      n._topic = topic;
      n._placed = true;
    });

    // 主题按大小轮流分到两条臂上；每条臂内部按主题顺序连续铺满，
    // 于是一个主题就是臂上的一段弧，而不是孤立的球团。
    var armTopics = [];
    for (var a0 = 0; a0 < ARMS; a0++) armTopics.push({ items: [], total: 0 });
    topicOrder.forEach(function (topic, ti) {
      var bucket = armTopics[ti % ARMS];
      bucket.items.push({ topic: topic, count: groups[topic].length, rank: ti });
      bucket.total += groups[topic].length;
    });

    armTopics.forEach(function (bucket, arm) {
      var cursor = 0;
      var denom = bucket.total || 1;
      bucket.items.forEach(function (item) {
        var list = groups[item.topic].filter(function (n) { return !n._placed; });
        var span = item.count / denom;
        var s0 = cursor;
        cursor += span;
        var ci = item.rank % PALETTE.length;

        list.forEach(function (n, i) {
          var f = s0 + span * ((i + 0.5) / Math.max(1, list.length));
          var seed = item.rank * 17.3 + i * 3.11;
          var rr = 46 + (MAX_R - 46) * Math.pow(Math.min(1, f), 0.84) +
            gauss(seed) * 5;
          var th = armTheta(rr, arm) +
            gauss(seed + 1.7) * (0.06 + 5 / Math.max(60, rr));
          var spread = rnd(seed + 4.4) < 0.16 ? 3.2 : 1;   // 少量星散到臂间
          var tOff = gauss(seed + 2.3) * 6.2;              // 沿臂方向
          var rOff = gauss(seed + 5.1) * 4.6 * spread;     // 垂直臂方向
          var tx = Math.cos(th + Math.PI / 2), ty = Math.sin(th + Math.PI / 2);
          var rx = Math.cos(th), ry = Math.sin(th);
          n._x = rx * rr + tx * tOff + rx * rOff;
          n._y = ry * rr + ty * tOff + ry * rOff;
          n._ci = ci;
          n._topic = item.topic;
        });
      });
    });

    nodes.sort(function (a, b) {
      return (a.importance || 0) - (b.importance || 0);
    });
  }

  /* ---------- 静态底图：深空辉光、旋臂尘埃、背景星野，一次绘制后随视图缩放 ---------- */
  function buildBackdrop() {
    bgR = MAX_R * 1.35;
    var S = 2;
    bg = document.createElement("canvas");
    bg.width = bg.height = Math.round(2 * bgR * S);
    var g = bg.getContext("2d");
    g.setTransform(S, 0, 0, S, bg.width / 2, bg.height / 2);

    // 银河整体冷光
    var base = g.createRadialGradient(0, 0, 0, 0, 0, bgR);
    base.addColorStop(0, "rgba(44,56,88,.55)");
    base.addColorStop(0.42, "rgba(22,30,52,.34)");
    base.addColorStop(1, "rgba(5,7,13,0)");
    g.fillStyle = base;
    g.fillRect(-bgR, -bgR, bgR * 2, bgR * 2);

    g.globalCompositeOperation = "lighter";

    // 核球暖光
    [[0, 0, 86, "rgba(255,232,198,.30)"],
     [0, 0, 190, "rgba(210,190,240,.10)"],
     [0, 0, 420, "rgba(120,150,220,.05)"]].forEach(function (b) {
      var gr = g.createRadialGradient(0, 0, 0, 0, 0, b[2]);
      gr.addColorStop(0, b[3]);
      gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr;
      g.beginPath();
      g.arc(0, 0, b[2], 0, TAU);
      g.fill();
    });

    // 旋臂辉光（沿对数螺旋逐步叠加）
    for (var arm = 0; arm < ARMS; arm++) {
      for (var s = 0; s <= 70; s++) {
        var r = 44 + (MAX_R * 1.12 - 44) * (s / 70);
        var th = armTheta(r, arm);
        var x = Math.cos(th) * r;
        var y = Math.sin(th) * r;
        var rad = 34 + r * 0.17;
        var gr2 = g.createRadialGradient(x, y, 0, x, y, rad);
        gr2.addColorStop(0, "rgba(136,166,218,.032)");
        gr2.addColorStop(1, "rgba(136,166,218,0)");
        g.fillStyle = gr2;
        g.beginPath();
        g.arc(x, y, rad, 0, TAU);
        g.fill();
      }
    }

    // 星云色块
    [[-170, 210, 200, "rgba(120,150,230,.055)"],
     [230, -180, 230, "rgba(180,140,220,.045)"],
     [30, 340, 210, "rgba(230,180,150,.035)"]].forEach(function (b) {
      var gr3 = g.createRadialGradient(b[0], b[1], 0, b[0], b[1], b[2]);
      gr3.addColorStop(0, b[3]);
      gr3.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr3;
      g.beginPath();
      g.arc(b[0], b[1], b[2], 0, TAU);
      g.fill();
    });

    // 背景星野：六成贴着旋臂，四成均匀撒在盘面
    for (var i = 0; i < 1500; i++) {
      var u = rnd(i * 1.73 + 0.31);
      var rr = 26 + (bgR - 40) * Math.pow(u, 0.6);
      var th2;
      if (rnd(i * 3.17 + 9.7) < 0.6) {
        th2 = armTheta(rr, Math.floor(rnd(i * 5.3 + 2.2) * ARMS)) +
          gauss(i * 7.9 + 4.4) * 0.55;
      } else {
        th2 = rnd(i * 11.3 + 6.1) * TAU;
      }
      var px = Math.cos(th2) * rr;
      var py = Math.sin(th2) * rr;
      var mag = rnd(i * 13.7 + 1.9);
      var sz = 0.7 + mag * 1.9;
      var col = PALETTE[Math.floor(rnd(i * 2.9 + 7.7) * 3) % 3];
      g.fillStyle = hueOf(col, 0.18 + mag * 0.55);
      g.fillRect(px - sz / 2, py - sz / 2, sz, sz);
    }

    // 核球星团：密集小球体
    for (var b2 = 0; b2 < 320; b2++) {
      var ang = rnd(b2 * 3.3 + 0.7) * TAU;
      var rad2 = Math.abs(gauss(b2 * 5.1 + 2.4)) * 62;
      var bx = Math.cos(ang) * rad2;
      var by = Math.sin(ang) * rad2 * 0.82;
      var m2 = rnd(b2 * 7.7 + 3.3);
      g.fillStyle = "rgba(255," + (238 - Math.round(m2 * 22)) + "," +
        (210 - Math.round(m2 * 40)) + "," + (0.25 + m2 * 0.6) + ")";
      g.fillRect(bx, by, 0.9 + m2 * 1.6, 0.9 + m2 * 1.6);
    }

    g.globalCompositeOperation = "source-over";
  }

  function fit() {
    if (!nodes.length) { view = { x: 0, y: 0, k: 1 }; return; }
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      minX = Math.min(minX, n._x); maxX = Math.max(maxX, n._x);
      minY = Math.min(minY, n._y); maxY = Math.max(maxY, n._y);
    });
    var pad = 56;
    var w = Math.max(1, innerWidth - pad * 2);
    var h = Math.max(1, innerHeight - pad * 2);
    var k = Math.min(w / Math.max(1, maxX - minX), h / Math.max(1, maxY - minY), 1.6);
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
    if (!highlightTopic) return true;
    return (n._topic || "其他") === highlightTopic;
  }

  function nodeScreenRadius(n) {
    var imp = n.importance || 0;
    var base = 0.85 + Math.pow(imp, 1.6) * 2.6;
    return Math.max(0.8, base * Math.min(1.7, Math.max(0.68, Math.pow(view.k, 0.45))));
  }

  function draw() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);

    if (bg) {
      var size = 2 * bgR * view.k;
      ctx.drawImage(
        bg,
        (view.x - bgR) * view.k + innerWidth / 2,
        (view.y - bgR) * view.k + innerHeight / 2,
        size, size
      );
    }

    var active = pinned || hovered;

    // 连线：同主题记忆的极淡曲线，像星流
    links.forEach(function (l) {
      var a = l._a, b = l._b;
      if (!a || !b || !hinted(a) || !hinted(b)) return;
      var sa = screenOf(a), sb = screenOf(b);
      var on = active && (active.id === a.id || active.id === b.id);
      if (!on) {
        if (sa.x < -60 || sa.x > innerWidth + 60 ||
            sa.y < -60 || sa.y > innerHeight + 60 ||
            sb.x < -60 || sb.x > innerWidth + 60 ||
            sb.y < -60 || sb.y > innerHeight + 60) return;
      }
      var c = PALETTE[a._ci == null ? 0 : a._ci];
      ctx.strokeStyle = on ? hueOf(c, 0.45, 4) : hueOf(c, 0.055);
      ctx.lineWidth = on ? 1.2 : 0.55;
      ctx.beginPath();
      ctx.moveTo(sa.x, sa.y);
      var cx = (sa.x + sb.x) / 2 + (sb.y - sa.y) * 0.14;
      var cy = (sa.y + sb.y) / 2 - (sb.x - sa.x) * 0.14;
      ctx.quadraticCurveTo(cx, cy, sb.x, sb.y);
      ctx.stroke();
    });

    // 光晕（叠加混合，聚成银河感）
    ctx.globalCompositeOperation = "lighter";
    nodes.forEach(function (n) {
      if (!hinted(n)) return;
      var p = screenOf(n);
      if (p.x < -40 || p.x > innerWidth + 40 || p.y < -40 || p.y > innerHeight + 40) return;
      var rs = nodeScreenRadius(n);
      var rad = rs * 4.8;
      ctx.globalAlpha = 0.10 + (n.importance || 0) * 0.26;
      ctx.drawImage(SPRITES[n._ci || 0], p.x - rad, p.y - rad, rad * 2, rad * 2);
    });
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";

    // 星芯 + 高亮
    nodes.forEach(function (n) {
      if (!hinted(n)) return;
      var p = screenOf(n);
      if (p.x < -20 || p.x > innerWidth + 20 || p.y < -20 || p.y > innerHeight + 20) return;
      var rs = nodeScreenRadius(n);
      var c = PALETTE[n._ci || 0];
      ctx.fillStyle = hueOf(c, 0.95, 8);
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(0.6, rs * 0.55), 0, TAU);
      ctx.fill();

      if ((n.importance || 0) > 0.9 && rs > 1.2) {
        ctx.strokeStyle = hueOf(c, 0.35, 6);
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(p.x - rs * 3.4, p.y);
        ctx.lineTo(p.x + rs * 3.4, p.y);
        ctx.moveTo(p.x, p.y - rs * 3.4);
        ctx.lineTo(p.x, p.y + rs * 3.4);
        ctx.stroke();
      }

      if (active && active.id === n.id) {
        ctx.strokeStyle = "rgba(240,246,255,.9)";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(p.x, p.y, rs + 3.5, 0, TAU);
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
    var shown = topicOrder.slice(0, 16);
    shown.forEach(function (topic) {
      var count = nodes.filter(function (n) { return n._topic === topic; }).length;
      var row = document.createElement("div");
      row.className = "row";
      var swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = hueOf(topicColor[topic], 0.95);
      swatch.style.boxShadow = "0 0 6px " + hueOf(topicColor[topic], 0.6);
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
    if (topicOrder.length > shown.length) {
      var more = document.createElement("div");
      more.className = "more";
      more.textContent = "另有 " + (topicOrder.length - shown.length) + " 个长尾主题";
      topicsEl.appendChild(more);
    }
  }

  function applyData(data) {
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
      statsEl.textContent = (src.scope ? "主私聊 · " : "") +
        nodes.length + " 条记忆 · " + links.length + " 条关联";
    }
    layout();
    buildBackdrop();
    fit();
    renderTopics();
    draw();
  }

  function start() {
    // 导出的离线单文件把数据内联在 window.__STARMAP_DATA__，不再请求接口
    if (window.__STARMAP_DATA__) {
      applyData(window.__STARMAP_DATA__);
      return;
    }
    fetch("/api/memories", { headers: { "X-Gate-Token": TOKEN } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(applyData)
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

  // 手机双指缩放：两个触点距离变化折算成缩放，锚点取两指中点
  var pointers = {};
  var pinch = null;

  function pinchInfo() {
    var ids = Object.keys(pointers);
    if (ids.length < 2) return null;
    var a = pointers[ids[0]];
    var b = pointers[ids[1]];
    return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
             mx: (a.x + b.x) / 2 - innerWidth / 2,
             my: (a.y + b.y) / 2 - innerHeight / 2 };
  }

  canvas.addEventListener("pointerdown", function (ev) {
    pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
    canvas.setPointerCapture(ev.pointerId);
    var info = pinchInfo();
    if (info) {
      pinch = { d: info.d, k: view.k };
      drag = null;
      return;
    }
    drag = { x: ev.clientX, y: ev.clientY, vx: view.x, vy: view.y, moved: false };
    canvas.classList.add("grabbing");
  });

  canvas.addEventListener("pointermove", function (ev) {
    if (pointers[ev.pointerId]) {
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
    }
    if (pinch) {
      var info = pinchInfo();
      if (info) {
        var k2 = Math.min(6, Math.max(0.15, pinch.k * (info.d / pinch.d)));
        view.x += info.mx / view.k - info.mx / k2;
        view.y += info.my / view.k - info.my / k2;
        view.k = k2;
        draw();
      }
      return;
    }
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
    delete pointers[ev.pointerId];
    if (Object.keys(pointers).length < 2) pinch = null;
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
