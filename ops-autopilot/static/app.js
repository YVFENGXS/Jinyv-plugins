(function () {
  "use strict";

  var token = new URLSearchParams(location.search).get("t") || "";
  var headers = { "X-Gate-Token": token };

  function levelText(level) {
    return { ok: "正常", warn: "注意", fail: "故障", info: "信息" }[level] || level;
  }

  function badge(level) {
    var span = document.createElement("span");
    span.className = "badge " + level;
    span.textContent = levelText(level);
    return span;
  }

  function renderStatus(data) {
    document.getElementById("meta").textContent =
      "库：" + (data.db || "?") + " · 巡检时间：" + (data.at || "?");

    var summary = document.getElementById("summary");
    summary.textContent = "";
    var title = document.createElement("span");
    title.className = "level";
    title.textContent = "总体：" + levelText(data.level || "info");
    var text = document.createElement("span");
    text.className = "text";
    text.textContent = (data.items || []).length + " 项检查";
    summary.appendChild(title);
    summary.appendChild(text);

    var rows = document.getElementById("rows");
    rows.textContent = "";
    (data.items || []).forEach(function (item) {
      var tr = document.createElement("tr");
      var a = document.createElement("td");
      a.textContent = item.name;
      var b = document.createElement("td");
      b.appendChild(badge(item.level));
      var c = document.createElement("td");
      c.textContent = String(item.detail);
      tr.appendChild(a);
      tr.appendChild(b);
      tr.appendChild(c);
      rows.appendChild(tr);
    });
  }

  function renderHistory(data) {
    var ul = document.getElementById("history");
    ul.textContent = "";
    (data.items || []).slice().reverse().forEach(function (item) {
      var li = document.createElement("li");
      var t = document.createElement("span");
      t.textContent = item.at || "";
      var l = document.createElement("span");
      l.textContent = "总体 " + levelText(item.level);
      var n = document.createElement("span");
      n.textContent = (item.items || []).length + " 项";
      li.appendChild(t);
      li.appendChild(l);
      li.appendChild(n);
      ul.appendChild(li);
    });
    if (!(data.items || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "还没有历史记录";
      ul.appendChild(empty);
    }
  }

  fetch("/api/status", { headers: headers })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d.error) {
        document.getElementById("meta").textContent = d.error;
        return;
      }
      renderStatus(d);
    })
    .catch(function (e) {
      document.getElementById("meta").textContent = "加载失败：" + e.message;
    });

  fetch("/api/history", { headers: headers })
    .then(function (r) { return r.json(); })
    .then(renderHistory)
    .catch(function () {});
})();
