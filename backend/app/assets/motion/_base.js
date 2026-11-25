// Shared by every motion effect: FX inputs -> DOM, then frame-exact seeking.
// Templates define fxBuild(FX, stage) to build their content, and optionally fxTick(t) for
// values that CSS can't animate (counting numbers). Times are seconds from the effect's start.
(function () {
  const FX = Object.assign({ title: "", items: [], numbers: [], unit: "", position: "top", accent: "#FF5A1F", duration: 3 }, window.FX || {});
  window.FX = FX;
  const root = document.documentElement;
  root.style.setProperty("--accent", FX.accent);
  // text that sits on the accent colour: dark on a light accent (yellow), white on a dark one
  const hex = (FX.accent || "#FF5A1F").replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  root.style.setProperty("--on-accent", 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 ? "#111" : "#fff");
  root.style.setProperty("--d", FX.duration + "s");

  window.el = function (tag, cls, text, parent) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  };
  // entrance delays spread over the first part of the effect, leaving time to read the last one
  window.stagger = function (k, n, first = 0.1, share = 0.55) {
    if (n <= 1) return first;
    return first + (k * Math.max(0, FX.duration * share - first)) / (n - 1);
  };
  window.ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
  window.fmt = function (v, decimals) {
    const d = decimals ?? (Math.abs(v) < 10 && v % 1 ? 1 : 0);
    return Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
  };

  window.fxSeek = function (t) {
    document.getAnimations().forEach((a) => { a.pause(); a.currentTime = t * 1000; });
    if (window.fxTick) window.fxTick(t);
  };

  function start() {
    const stage = el("div", "stage " + (FX.position || "top"), null, document.body);
    if (window.fxBuild) window.fxBuild(FX, stage);
    getComputedStyle(document.body).opacity; // start the CSS animations now
    // the fonts the content uses load now; wait for them so frame 0 already has them
    document.fonts.ready.then(() => { window.fxSeek(0); window.fxReady = true; });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
