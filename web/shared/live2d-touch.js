(function () {
  const STYLE_HREF = "/assets/shared/live2d-touch.css?v=5d88d16189";
  const TAP_COOLDOWN_MS = 380;
  let audioCtx = null;
  let lastTapAt = 0;

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function ensureCss() {
    if (document.querySelector("link[data-live2d-touch]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = STYLE_HREF;
    link.dataset.live2dTouch = "1";
    document.head.appendChild(link);
  }

  function audio() {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    if (!audioCtx) audioCtx = new Ctor();
    if (audioCtx.state === "suspended") {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  }

  function tone(ctx, freq, when, duration, type, volume) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, when);
    gain.gain.setValueAtTime(0.0001, when);
    gain.gain.exponentialRampToValueAtTime(volume, when + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(when);
    osc.stop(when + duration + 0.02);
  }

  function playSfx(kind) {
    const ctx = audio();
    if (!ctx) return;
    const run = () => {
      const now = ctx.currentTime;
      if (kind === "head") {
        tone(ctx, 988, now, 0.12, "sine", 0.05);
        tone(ctx, 1480, now + 0.04, 0.14, "triangle", 0.035);
        tone(ctx, 1976, now + 0.08, 0.1, "sine", 0.02);
        return;
      }
      tone(ctx, 523, now, 0.11, "sine", 0.045);
      tone(ctx, 784, now + 0.05, 0.13, "triangle", 0.03);
      tone(ctx, 1046, now + 0.09, 0.1, "sine", 0.018);
    };
    if (ctx.state === "suspended") {
      ctx.resume().then(run).catch(() => {});
      return;
    }
    run();
  }

  function sparkles(host, x, y, palette) {
    const layer = host.querySelector(".live2d-sparkles") || host.appendChild((() => {
      const node = document.createElement("div");
      node.className = "live2d-sparkles";
      node.setAttribute("aria-hidden", "true");
      return node;
    })());
    const color = palette === "pink" ? "#ffd0e6" : "#ffe7b4";
    for (let i = 0; i < 8; i += 1) {
      const spark = document.createElement("span");
      spark.className = "live2d-spark";
      const angle = (Math.PI * 2 * i) / 8;
      const dist = 18 + Math.random() * 28;
      spark.style.left = `${x}px`;
      spark.style.top = `${y}px`;
      spark.style.color = color;
      spark.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
      spark.style.setProperty("--dy", `${Math.sin(angle) * dist - 10}px`);
      layer.appendChild(spark);
      window.setTimeout(() => spark.remove(), 720);
    }
  }

  function playTapMotion(l2d, kind) {
    if (!l2d || typeof l2d.playMotion !== "function") return "";
    const groups = kind === "head"
      ? ["flick_head", "surprised", "tap_body", "happy"]
      : ["tap_body", "happy", "idle"];
    let used = "";
    groups.forEach((group) => {
      if (used) return;
      try {
        l2d.playMotion(group);
        used = group;
      } catch (_) { /* group may be missing */ }
    });
    if (typeof l2d.setExpression === "function") {
      try {
        l2d.setExpression(kind === "head" ? "surprised01" : "smile01");
      } catch (_) { /* expression names vary */ }
    }
    return used;
  }

  function bind(stage, options) {
    if (!stage || stage.dataset.live2dTouch === "1") return;
    const opts = options || {};
    stage.dataset.live2dTouch = "1";
    ensureCss();
    stage.classList.add("live2d-touch-stage");
    if (!stage.querySelector(".live2d-tap-ring")) {
      const ring = document.createElement("div");
      ring.className = "live2d-tap-ring";
      ring.setAttribute("aria-hidden", "true");
      stage.appendChild(ring);
    }
    if (!stage.querySelector(".live2d-touch-hint")) {
      const hint = document.createElement("div");
      hint.className = "live2d-touch-hint";
      hint.textContent = "点击互动";
      stage.appendChild(hint);
    }
    stage.addEventListener("pointerdown", (event) => {
      if (event.button) return;
      const now = Date.now();
      if (now - lastTapAt < TAP_COOLDOWN_MS) return;
      lastTapAt = now;
      const rect = stage.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const kind = (y / Math.max(rect.height, 1)) < 0.38 ? "head" : "body";
      const widget = typeof opts.getWidget === "function" ? opts.getWidget() : null;
      playTapMotion(widget && widget.l2d, kind);
      if (!reducedMotion()) {
        playSfx(kind);
        sparkles(stage, x, y, typeof opts.tone === "function" ? opts.tone() : opts.tone);
      }
      stage.classList.remove("is-tapped");
      void stage.offsetWidth;
      stage.classList.add("is-tapped");
      const hint = stage.querySelector(".live2d-touch-hint");
      if (hint) hint.classList.add("is-hidden");
      if (typeof opts.onTap === "function") opts.onTap(kind);
    });
  }

  window.Live2dTouch = { bind, playSfx };
})();
