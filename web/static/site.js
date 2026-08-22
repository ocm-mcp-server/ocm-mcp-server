// SPDX-FileCopyrightText: 2026 Sandeep Bazar
// SPDX-License-Identifier: Apache-2.0
//
// No framework, no CDN. Every behaviour degrades to a working static page if
// this file fails to load.
//
// Motion policy: the OS preference is the default, and the header toggle lets a
// visitor override it in either direction. Someone who runs macOS "Reduce
// motion" system-wide but wants the full design here can have it, and someone
// on a machine with no such setting can still turn motion off.

(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const root = document.documentElement;

  const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const readPref = () => {
    try {
      return localStorage.getItem("motion");
    } catch {
      return null; // private mode: fall back to the OS preference
    }
  };
  // Explicit choice wins; otherwise follow the OS.
  const motionAllowed = () => {
    const pref = readPref();
    if (pref === "full") return true;
    if (pref === "reduced") return false;
    return !motionQuery.matches;
  };
  let moving = motionAllowed();
  const reduced = !moving;

  /* ------------------------------------------------------------- theme -- */
  // Applied inline in <head> before paint to avoid a flash; this only wires
  // the toggle and keeps mermaid in sync.
  function setTheme(next) {
    root.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch { /* private mode: fall back to per-session only */ }
    renderMermaid(true);
  }

  $("#theme")?.addEventListener("click", () => {
    setTheme(root.dataset.theme === "light" ? "dark" : "light");
  });

  /* ------------------------------------------------------------ motion -- */
  const motionBtn = $("#motion");
  function syncMotionBtn() {
    if (!motionBtn) return;
    motionBtn.setAttribute("aria-pressed", String(moving));
    motionBtn.setAttribute(
      "aria-label",
      moving ? "Turn animations off" : "Turn animations on",
    );
    motionBtn.dataset.state = moving ? "on" : "off";
  }
  syncMotionBtn();

  motionBtn?.addEventListener("click", () => {
    moving = !moving;
    const next = moving ? "full" : "reduced";
    root.dataset.motion = next;
    try {
      localStorage.setItem("motion", next);
    } catch { /* private mode: this session only */ }
    syncMotionBtn();
    // Anything still waiting to be revealed would otherwise sit at opacity 0
    // once its transition has been flattened.
    if (!moving) revealables.forEach((el) => el.classList.add("in"));
  });

  /* ---------------------------------------------------------- progress -- */
  const bar = $(".progress");
  if (bar) {
    const onScroll = () => {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      bar.style.setProperty("--p", max > 0 ? String(h.scrollTop / max) : "0");
    };
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ------------------------------------------------------------ reveal -- */
  const revealables = $$("[data-reveal]");
  // Only a missing IntersectionObserver forces everything visible up front.
  // Under reduced motion the fade still runs - `--move: 0` has already removed
  // the travel, and opacity alone is not what triggers motion sensitivity.
  if (!("IntersectionObserver" in window)) {
    revealables.forEach((el) => el.classList.add("in"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          e.target.classList.add("in");
          io.unobserve(e.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    revealables.forEach((el) => io.observe(el));
  }

  /* ------------------------------------------------------------ counts -- */
  // Counts up to the number already in the DOM, so the real value is present
  // even with JS disabled.
  $$("[data-count]").forEach((el) => {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target) || reduced) return;
    const suffix = el.dataset.suffix || "";
    let started = false;
    const run = () => {
      if (started) return;
      started = true;
      const t0 = performance.now();
      const dur = 1100;
      const tick = (now) => {
        const p = Math.min(1, (now - t0) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = Math.round(target * eased) + suffix;
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };
    if (!("IntersectionObserver" in window)) return run();
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => e.isIntersecting && (run(), io.disconnect())),
      { threshold: 0.5 },
    );
    io.observe(el);
  });

  /* ---------------------------------------------------------- scrollspy -- */
  const tocLinks = $$(".toc a");
  if (tocLinks.length && "IntersectionObserver" in window) {
    const byId = new Map(tocLinks.map((a) => [decodeURIComponent(a.hash.slice(1)), a]));
    const heads = $$(".prose h2[id], .prose h3[id]").filter((h) => byId.has(h.id));
    let active = null;
    const spy = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          const link = byId.get(e.target.id);
          if (!link || link === active) return;
          active?.classList.remove("is-active");
          link.classList.add("is-active");
          active = link;
        });
      },
      { rootMargin: "-72px 0px -72% 0px" },
    );
    heads.forEach((h) => spy.observe(h));
  }

  /* --------------------------------------------------------------- copy -- */
  $$(".prose pre").forEach((pre) => {
    const btn = document.createElement("button");
    btn.className = "copy";
    btn.type = "button";
    btn.textContent = "copy";
    btn.setAttribute("aria-label", "Copy code to clipboard");
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(pre.querySelector("code")?.innerText ?? "");
        btn.textContent = "copied";
        btn.classList.add("ok");
      } catch {
        btn.textContent = "press ⌘C";
      }
      setTimeout(() => {
        btn.textContent = "copy";
        btn.classList.remove("ok");
      }, 1600);
    });
    pre.appendChild(btn);
  });

  /* ------------------------------------------------------------ sidebar -- */
  const side = $(".side");
  const sideBtn = $(".side__toggle");
  if (side && sideBtn) {
    const sync = () => {
      const wide = innerWidth > 900;
      side.hidden = !wide;
      sideBtn.setAttribute("aria-expanded", String(wide));
    };
    sideBtn.addEventListener("click", () => {
      const open = side.hidden;
      side.hidden = !open;
      sideBtn.setAttribute("aria-expanded", String(open));
    });
    addEventListener("resize", sync);
    sync();
  }

  /* ------------------------------------------------------------ mermaid -- */
  // 2.7 MB of vendored library: loaded only on pages that have a diagram, and
  // only when one is about to enter the viewport.
  const wraps = $$(".mermaid-wrap");
  let mermaidReady = null;

  function mermaidTheme() {
    const light = root.dataset.theme === "light";
    return {
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily:
        'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      // lineColor is deliberately high-contrast in both themes: mermaid's
      // defaults are mid-greys that vanish against these backgrounds.
      themeVariables: light
        ? {
            background: "#ffffff",
            primaryColor: "#eef2f9",
            primaryTextColor: "#0d1428",
            primaryBorderColor: "#4f46e5",
            lineColor: "#334155",
            textColor: "#0d1428",
            secondaryColor: "#e0e7ff",
            tertiaryColor: "#f1f5f9",
          }
        : {
            background: "#101736",
            primaryColor: "#1c2547",
            primaryTextColor: "#eef2ff",
            primaryBorderColor: "#8ea2ff",
            lineColor: "#b8c6ee",
            textColor: "#eef2ff",
            secondaryColor: "#1e2a52",
            tertiaryColor: "#141a33",
          },
    };
  }

  function loadMermaid() {
    if (mermaidReady) return mermaidReady;
    mermaidReady = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = root.dataset.base + "vendor/mermaid.min.js";
      s.onload = () => resolve(window.mermaid);
      s.onerror = () => reject(new Error("mermaid failed to load"));
      document.head.appendChild(s);
    });
    return mermaidReady;
  }

  async function renderMermaid(rerender = false) {
    if (!wraps.length) return;
    if (rerender && !mermaidReady) return;
    let mermaid;
    try {
      mermaid = await loadMermaid();
    } catch {
      // Leave the source visible rather than showing an empty box.
      wraps.forEach((w) => {
        w.dataset.state = "done";
        const n = w.querySelector(".mermaid");
        if (n) n.textContent = n.dataset.src || n.textContent;
      });
      return;
    }
    mermaid.initialize(mermaidTheme());
    for (const [i, wrap] of wraps.entries()) {
      const node = wrap.querySelector(".mermaid");
      if (!node) continue;
      const src = node.dataset.src;
      if (!src) continue;
      try {
        const { svg } = await mermaid.render(`mmd-${i}-${rerender ? Date.now() : 0}`, src);
        // innerHTML is deliberate and bounded: the diagram source is markdown
        // committed to this repository (never user input), and mermaid runs
        // with securityLevel "strict", which strips HTML from node labels and
        // disables click handlers. Nothing here crosses a trust boundary.
        node.innerHTML = svg;
        wrap.dataset.state = "done";
      } catch {
        node.textContent = src;
        wrap.dataset.state = "done";
      }
    }
  }

  /* ----------------------------------------------------------- lightbox -- */
  // Diagrams are dense; at column width the labels are legible but the detail
  // is not. Click opens a full-viewport copy that can be scrolled.
  let box = null;

  function openZoom(source) {
    if (!box) {
      box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML =
        '<button class="lightbox__close" type="button" aria-label="Close">&times;</button>' +
        '<div class="lightbox__stage"></div>';
      box.addEventListener("click", (e) => {
        if (e.target === box || (e.target instanceof Element && e.target.closest(".lightbox__close"))) {
          closeZoom();
        }
      });
      document.body.appendChild(box);
    }
    const stage = box.querySelector(".lightbox__stage");
    if (!stage) return;
    stage.replaceChildren(source.cloneNode(true));
    box.dataset.open = "true";
    document.body.style.overflow = "hidden";
    box.querySelector(".lightbox__close")?.focus();
  }

  function closeZoom() {
    if (!box) return;
    box.dataset.open = "false";
    document.body.style.overflow = "";
  }

  addEventListener("keydown", (e) => e.key === "Escape" && closeZoom());

  function makeZoomable(el, inner) {
    el.classList.add("zoomable");
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", "Expand to full size");
    const hint = document.createElement("span");
    hint.className = "zoomhint";
    hint.textContent = "click to expand";
    el.appendChild(hint);
    const go = () => {
      const target = inner();
      if (target) openZoom(target);
    };
    el.addEventListener("click", go);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        go();
      }
    });
  }

  $$(".prose img").forEach((img) => {
    const fig = document.createElement("figure");
    img.replaceWith(fig);
    fig.appendChild(img);
    fig.style.position = "relative";
    fig.style.margin = "1.6em 0";
    makeZoomable(fig, () => img);
  });

  if (wraps.length) {
    wraps.forEach((w) => makeZoomable(w, () => w.querySelector("svg")));
    if (!("IntersectionObserver" in window)) {
      renderMermaid();
    } else {
      const mio = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            mio.disconnect();
            renderMermaid();
          }
        },
        { rootMargin: "400px" },
      );
      wraps.forEach((w) => mio.observe(w));
    }
  }
})();
