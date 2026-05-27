import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Animate-presence hook: delays unmount until a CSS transition/animation ends.
 *
 * Returns `{ mounted, visible }`:
 *   - `mounted` — whether the element should exist in the DOM
 *   - `visible` — whether the "open" class should be applied
 *
 * Typical usage:
 * ```tsx
 * const { mounted, visible } = usePresence(open);
 * if (!mounted) return null;
 * return <div className={visible ? "opacity-100" : "opacity-0"} onTransitionEnd={...} />
 * ```
 */
export function usePresence(show: boolean, duration = 200) {
  // Two state slots: ``mounted`` controls whether the element exists
  // in the DOM, ``visible`` controls the open class. They are
  // intentionally desynchronised on the OPEN transition so the
  // initial render lands with ``mounted=true, visible=false`` (the
  // closed-state class), and a next-frame effect flips ``visible``
  // to ``true``. Without this the open-state class is applied on
  // the very first paint and the CSS transition has nothing to
  // animate from — symptom: opens abruptly, closes smoothly.
  const [mounted, setMounted] = useState(show);
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const raf = useRef<number | null>(null);

  useEffect(() => {
    clearTimeout(timer.current);
    if (raf.current !== null) {
      cancelAnimationFrame(raf.current);
      raf.current = null;
    }
    if (show) {
      setMounted(true);
      // Flip ``visible`` on the next frame so the closed-state class
      // is painted at least once before the open-state class — that's
      // the frame the CSS transition lerps from.
      raf.current = requestAnimationFrame(() => {
        raf.current = requestAnimationFrame(() => {
          setVisible(true);
        });
      });
    } else {
      setVisible(false);
      timer.current = setTimeout(() => setMounted(false), duration);
    }
    return () => {
      clearTimeout(timer.current);
      if (raf.current !== null) {
        cancelAnimationFrame(raf.current);
        raf.current = null;
      }
    };
  }, [show, duration]);

  return { mounted, visible };
}

/**
 * Simple vertical-drag hook for bottom-sheet dismiss.
 *
 * Returns props to spread onto the draggable element.
 */
export function useVerticalDrag(onDismiss: () => void, threshold = 120) {
  const startY = useRef(0);
  const currentY = useRef(0);
  const dragging = useRef(false);
  const elRef = useRef<HTMLDivElement | null>(null);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    startY.current = e.clientY;
    currentY.current = 0;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dy = Math.max(0, e.clientY - startY.current);
    currentY.current = dy;
    if (elRef.current) {
      elRef.current.style.transform = `translateY(${dy}px)`;
    }
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
    if (currentY.current > threshold) {
      onDismiss();
    }
    if (elRef.current) {
      // V13.1 — clear the inline transform rather than pinning it to
      // ``translateY(0)`` so the consumer's open/closed Tailwind
      // class (``translate-y-0`` vs ``translate-y-full``) regains
      // control. Pinning it inline meant a drag-dismissed sheet
      // visually stuck around because its inline style overrode
      // the parent's "closed" class on the very next render.
      elRef.current.style.transition = "transform .2s ease-out";
      elRef.current.style.transform = "";
      const el = elRef.current;
      const cleanup = () => {
        el.style.transition = "";
      };
      el.addEventListener("transitionend", cleanup, { once: true });
    }
    currentY.current = 0;
  }, [onDismiss, threshold]);

  return { elRef, onPointerDown, onPointerMove, onPointerUp };
}

/**
 * Horizontal-swipe hook for swipe-to-action gestures.
 */
export function useHorizontalSwipe(onSwipe: () => void, threshold = 50) {
  const startX = useRef(0);
  const currentX = useRef(0);
  const dragging = useRef(false);
  const elRef = useRef<HTMLDivElement | null>(null);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    startX.current = e.clientX;
    currentX.current = 0;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return;
    const dx = Math.min(0, e.clientX - startX.current);
    currentX.current = dx;
    if (elRef.current) {
      elRef.current.style.transform = `translateX(${dx}px)`;
    }
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
    if (Math.abs(currentX.current) > threshold) {
      onSwipe();
    }
    if (elRef.current) {
      // V13.1 — clear the inline transform so the consumer's
      // open/closed class regains control after a swipe (mirrors the
      // ``useVerticalDrag`` fix; same root-cause).
      elRef.current.style.transition = "transform .2s ease-out";
      elRef.current.style.transform = "";
      const el = elRef.current;
      const cleanup = () => {
        el.style.transition = "";
      };
      el.addEventListener("transitionend", cleanup, { once: true });
    }
    currentX.current = 0;
  }, [onSwipe, threshold]);

  return { elRef, onPointerDown, onPointerMove, onPointerUp };
}

/**
 * Scroll-linked transform hook for parallax effects.
 */
export function useScrollTransform(
  range: [number, number],
  outputY: [number, number],
  outputOpacity: [number, number],
) {
  const [style, setStyle] = useState({ y: outputY[0], opacity: outputOpacity[0] });

  useEffect(() => {
    function onScroll() {
      const scrollY = window.scrollY;
      const [minS, maxS] = range;
      const t = Math.min(1, Math.max(0, (scrollY - minS) / (maxS - minS)));
      setStyle({
        y: outputY[0] + (outputY[1] - outputY[0]) * t,
        opacity: outputOpacity[0] + (outputOpacity[1] - outputOpacity[0]) * t,
      });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [range, outputY, outputOpacity]);

  return style;
}

/** Compute a stagger delay style prop from an item index. */
export function staggerDelay(index: number, stepMs = 30, maxMs = 300) {
  return { animationDelay: `${Math.min(index * stepMs, maxMs)}ms` };
}
