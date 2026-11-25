import "./cursor-cat.css";

import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/cn";

type Mode = "idle" | "sit" | "walk" | "run" | "jump" | "sleep";
type Floor = "hero" | "screen";

const STOP_GAP = 70; // how far from the cursor the cat stops (px)
const MAX_SPEED = 560; // px/s when chasing
const PATROL_SPEED = 140; // px/s when wandering (touch devices / before first mouse move)
const SIT_AFTER_MS = 900; // stand still this long and she sits down
const SLEEP_AFTER_MS = 8000;
const SCREEN_FLOOR_GAP = 12; // px above the bottom edge of the viewport

const MESSAGES = [
  "Purr-fect deal spotted!",
  "Psst… Flipkart's cheaper today",
  "I only chase the best prices",
  "Meow! Try searching “sneakers”",
  "Wake me when prices drop",
  "Comparing 6 stores, paws down",
  "Wait for me!",
];

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

interface Jump {
  from: number;
  start: number;
  duration: number;
  height: number;
}

/**
 * Mascot that follows the cursor. It stands on the hero's floor line while that is on screen;
 * once the floor scrolls away it leaps down to the bottom of the viewport and keeps you company
 * (bounding along while you scroll), jumping back onto the hero floor when you return.
 *
 * Rendered in a portal (page wrappers use transforms, which would break position: fixed) and
 * animated off-React with refs + rAF, so it never re-renders per frame.
 */
export function CursorCat({ className }: { className?: string }) {
  const heroFloorRef = useRef<HTMLDivElement>(null);
  const catRef = useRef<HTMLDivElement>(null);
  const flipRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const headRef = useRef<SVGGElement>(null);
  const pupilsRef = useRef<SVGGElement>(null);
  const [bubble, setBubble] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const heroFloor = heroFloorRef.current;
    const cat = catRef.current;
    const flip = flipRef.current;
    const svg = svgRef.current;
    const head = headRef.current;
    const pupils = pupilsRef.current;
    if (!mounted || !heroFloor || !cat || !flip || !svg || !head || !pupils) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const now0 = performance.now();

    let pointer: { x: number; y: number } | null = null;
    let lastMoveAt = now0;
    let lastScrollAt = -Infinity;
    let x = document.documentElement.clientWidth * 0.7;
    let v = 0;
    let y = window.innerHeight - SCREEN_FLOOR_GAP; // feet position (viewport px)
    let floor: Floor | null = null;
    let jump: Jump | null = null;
    let facing = -1;
    let mode: Mode = "idle";
    let chasing = false;
    let stillSince = now0;
    let patrolTarget = x;
    let nextPatrolAt = now0 + 2500;
    let lastBubbleAt = -Infinity;
    let bubbleTimer = 0;
    let msg = Math.floor(Math.random() * MESSAGES.length);
    let last = now0;
    let raf = 0;

    cat.dataset.mode = mode;

    const setMode = (next: Mode) => {
      if (next === mode) return;
      mode = next;
      cat.dataset.mode = next;
    };

    const say = (now: number, text?: string) => {
      if (now - lastBubbleAt < 9000) return;
      lastBubbleAt = now;
      setBubble(text ?? MESSAGES[msg++ % MESSAGES.length]!);
      window.clearTimeout(bubbleTimer);
      bubbleTimer = window.setTimeout(() => setBubble(null), 2600);
    };

    const startJump = (now: number, height: number, distance: number) => {
      if (reduced) return;
      jump = { from: y, start: now, duration: clamp(0.38 + distance / 1500, 0.38, 0.8) * 1000, height };
    };

    const wake = () => {
      if (mode === "sleep") {
        setMode("idle");
        startJump(performance.now(), 20, 0);
      }
    };

    const onPointer = (e: PointerEvent) => {
      pointer = { x: e.clientX, y: e.clientY };
      lastMoveAt = performance.now();
      wake();
    };

    const onScroll = () => {
      lastScrollAt = performance.now();
      lastMoveAt = lastScrollAt;
      wake();
    };

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      const half = cat.offsetWidth / 2;
      const minX = half;
      const maxX = Math.max(minX, vw - half);

      // --- which floor are we on? (hysteresis avoids flip-flopping at the edges) ---------
      const heroY = heroFloor.getBoundingClientRect().top;
      const screenY = vh - SCREEN_FLOOR_GAP;
      const heroUsable =
        floor === "hero" ? heroY >= vh * 0.22 && heroY <= vh - 4 : heroY >= vh * 0.32 && heroY <= vh - 24;
      const nextFloor: Floor = heroUsable ? "hero" : "screen";
      const targetY = nextFloor === "hero" ? heroY : screenY;

      if (floor === null) {
        y = targetY;
      } else if (nextFloor !== floor) {
        const dy = targetY - y;
        // Leap: higher arc for bigger drops, always at least a little hop up first.
        startJump(now, Math.max(36, Math.abs(dy) * 0.22), Math.abs(dy));
        if (nextFloor === "screen") say(now, "Wait for me!");
      } else if (!jump && nextFloor === "screen" && now - lastScrollAt < 120) {
        startJump(now, 16 + Math.random() * 12, 0); // bound along while you scroll
      }
      floor = nextFloor;

      // --- vertical motion ----------------------------------------------------------------
      if (jump) {
        const p = Math.min(1, (now - jump.start) / jump.duration);
        const base = jump.from + (targetY - jump.from) * p; // land on the (possibly moving) floor
        y = base - jump.height * 4 * p * (1 - p);
        if (p >= 1) {
          jump = null;
          y = targetY;
        }
      } else {
        y = targetY; // stand on it (rides along with the hero floor as it scrolls)
      }

      // --- horizontal motion --------------------------------------------------------------
      if (!reduced && mode !== "sleep") {
        let goal: number;
        let limit = MAX_SPEED;
        if (pointer) {
          goal = pointer.x + (pointer.x > x ? -STOP_GAP : STOP_GAP);
        } else {
          if (now > nextPatrolAt) {
            patrolTarget = minX + Math.random() * (maxX - minX);
            nextPatrolAt = now + 5000 + Math.random() * 4000;
          }
          goal = patrolTarget;
          limit = PATROL_SPEED;
        }
        const dist = clamp(goal, minX, maxX) - x;
        const desired = Math.abs(dist) < 3 ? 0 : clamp(dist * 3.2, -limit, limit);
        // Rate ≈ 4× the gain keeps the spring critically damped: no overshoot past the cursor.
        v += (desired - v) * Math.min(1, dt * 14);
      } else {
        v *= 0.8;
      }
      x = clamp(x + v * dt, minX, maxX);

      // --- state --------------------------------------------------------------------------
      const speed = Math.abs(v);
      if (jump || speed > 28) stillSince = now;
      if (jump) setMode("jump");
      else if (mode !== "sleep") {
        if (speed > 300) setMode("run");
        else if (speed > 28) setMode("walk");
        else if (mode === "sit" || now - stillSince > SIT_AFTER_MS) setMode("sit");
        else setMode("idle");
      }

      if (speed > 28) {
        facing = Math.sign(v);
        chasing = true;
      } else {
        if (pointer && Math.abs(pointer.x - x) > 24) facing = pointer.x > x ? 1 : -1;
        if (chasing && !jump) {
          chasing = false;
          if (pointer) say(now);
        }
      }
      if (pointer && mode === "sit" && now - lastMoveAt > SLEEP_AFTER_MS) setMode("sleep");

      cat.style.transform = `translate3d(${(x - half).toFixed(1)}px,${(y - cat.offsetHeight + 4).toFixed(1)}px,0)`;
      flip.style.transform = `scaleX(${facing})`;
      const side = facing > 0 ? "right" : "left";
      if (cat.dataset.facing !== side) cat.dataset.facing = side;

      // --- gaze ---------------------------------------------------------------------------
      if (pointer && mode !== "sleep") {
        const hb = head.getBoundingClientRect();
        const dx = pointer.x - (hb.left + hb.width / 2);
        const dy = pointer.y - (hb.top + hb.height / 2);
        const d = Math.hypot(dx, dy) || 1;
        const reach = 2.6 * Math.min(1, d / 120);
        // The SVG is mirrored when facing left, so mirror the horizontal offset too.
        pupils.setAttribute("transform", `translate(${((dx / d) * reach * facing).toFixed(2)} ${((dy / d) * reach).toFixed(2)})`);
        head.style.transform = `rotate(${clamp(dy / 28, -14, 10).toFixed(1)}deg)`;
      } else {
        pupils.setAttribute("transform", "translate(0 0)");
        head.style.transform = "";
      }

      raf = requestAnimationFrame(frame);
    };

    // Pause when the tab is hidden.
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };

    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("pointerdown", onPointer, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(bubbleTimer);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [mounted]);

  return (
    <>
      {/* The hero floor line: the cat stands here while it's on screen. */}
      <div aria-hidden className={cn("pointer-events-none absolute inset-x-0 bottom-0 h-36", className)}>
        <div ref={heroFloorRef} className="absolute inset-x-[6%] bottom-[18px] h-px bg-linear-to-r from-transparent via-ink-300/80 to-transparent" />
      </div>

      {mounted &&
        createPortal(
          <div aria-hidden className="pointer-events-none fixed inset-0 z-40 overflow-hidden select-none">
            <div ref={catRef} className="cursor-cat absolute top-0 left-0 w-[112px] sm:w-[140px]">
              {bubble && (
                <div className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2">
                  <div
                    key={bubble}
                    className="relative animate-scale-in rounded-2xl border border-ink-100 bg-white px-3 py-1.5 text-xs font-semibold whitespace-nowrap text-ink-800 shadow-lift"
                  >
                    {bubble}
                    <span className="absolute -bottom-1.5 left-1/2 size-3 -translate-x-1/2 rotate-45 border-r border-b border-ink-100 bg-white" />
                  </div>
                </div>
              )}

              <div className="cat-zzz absolute -top-2 right-2 font-logo text-base font-semibold text-brand-500">
                <span>z</span>
                <span>z</span>
                <span>z</span>
              </div>

              <div ref={flipRef} className="cat-flip">
                <CatSvg svgRef={svgRef} headRef={headRef} pupilsRef={pupilsRef} />
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

function CatSvg({
  svgRef,
  headRef,
  pupilsRef,
}: {
  svgRef: RefObject<SVGSVGElement | null>;
  headRef: RefObject<SVGGElement | null>;
  pupilsRef: RefObject<SVGGElement | null>;
}) {
  return (
    <svg ref={svgRef} viewBox="0 0 140 110" className="block h-auto w-full overflow-visible">
      <ellipse className="cat-shadow" cx="70" cy="104" rx="44" ry="4" />
      <g className="cat-body">
        {/* Standing rig: walk / run / jump */}
        <g className="cat-stand">
          <g className="cat-tail">
            <path d="M34 62C14 58 6 38 18 22" />
          </g>
          <rect className="cat-leg cat-leg--far cat-leg--b" x="38" y="68" width="9" height="34" rx="4.5" />
          <rect className="cat-leg cat-leg--far cat-leg--f" x="88" y="68" width="9" height="34" rx="4.5" />
          <ellipse className="cat-torso" cx="68" cy="64" rx="38" ry="20" />
          <rect className="cat-leg cat-leg--near cat-leg--a" x="46" y="70" width="10" height="33" rx="5" />
          <rect className="cat-leg cat-leg--near cat-leg--c" x="96" y="70" width="10" height="33" rx="5" />
        </g>

        {/* Sitting rig: haunches down, front legs straight, tail wrapped round the paws */}
        <g className="cat-sit">
          <rect className="cat-fill-far" x="96" y="74" width="8" height="30" rx="4" />
          <ellipse className="cat-fill" cx="84" cy="84" rx="22" ry="20" />
          <ellipse className="cat-fill-far" cx="83" cy="92" rx="15" ry="11" />
          <ellipse className="cat-fill-soft" cx="93" cy="102.5" rx="7" ry="2.6" />
          <ellipse className="cat-fill" cx="101" cy="72" rx="15" ry="22" />
          <rect className="cat-fill" x="106" y="76" width="9" height="28" rx="4.5" />
          <ellipse className="cat-fill-soft" cx="110.5" cy="103" rx="5.5" ry="2.4" />
          <g className="cat-sit-tail">
            <path d="M66 96C56 106 80 109 96 107C106 106 114 104 121 100" />
          </g>
        </g>

        <g ref={headRef} className="cat-head">
          <g className="cat-head-inner">
            <polygon className="cat-ear" points="91,36 94,12 108,28" />
            <polygon className="cat-ear" points="111,27 124,10 128,35" />
            <polygon className="cat-ear-inner" points="95.5,31 97,18.5 104,27" />
            <polygon className="cat-ear-inner" points="114.5,27 122.5,17 124,31" />
            <circle className="cat-skull" cx="110" cy="44" r="20" />

            <ellipse className="cat-eye" cx="103" cy="41" rx="4.4" ry="5.1" />
            <ellipse className="cat-eye" cx="117" cy="41" rx="4.4" ry="5.1" />
            <g ref={pupilsRef}>
              <circle className="cat-pupil" cx="103" cy="41.5" r="2.5" />
              <circle className="cat-pupil" cx="117" cy="41.5" r="2.5" />
              <circle className="cat-glint" cx="104" cy="40.2" r="0.8" />
              <circle className="cat-glint" cx="118" cy="40.2" r="0.8" />
            </g>
            <g className="cat-lids">
              <rect x="98.2" y="35.6" width="9.6" height="11" rx="4.8" />
              <rect x="112.2" y="35.6" width="9.6" height="11" rx="4.8" />
            </g>
            <path className="cat-sleep-eyes" d="M99 42q4 3 8 0M113 42q4 3 8 0" />

            <path className="cat-nose" d="M107.5 48.5h5l-2.5 3z" />
            <path className="cat-mouth" d="M110 51.5q-1.8 3-4.3 1.5M110 51.5q1.8 3 4.3 1.5" />
            <g className="cat-whiskers">
              <path d="M119 49.5L136 46.5" />
              <path d="M119 52.5L136 54.5" />
              <path d="M101 49.5L84 46.5" />
              <path d="M101 52.5L84 54.5" />
            </g>
            <path className="cat-collar" d="M94 57Q103 65 116 62" />
            <circle className="cat-tag" cx="104.5" cy="63" r="3" />
          </g>
        </g>
      </g>
    </svg>
  );
}
