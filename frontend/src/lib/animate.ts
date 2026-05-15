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
  const [mounted, setMounted] = useState(show);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(timer.current);
    if (show) {
      setMounted(true);
    } else {
      timer.current = setTimeout(() => setMounted(false), duration);
    }
    return () => clearTimeout(timer.current);
  }, [show, duration]);

  return { mounted, visible: show && mounted };
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
      elRef.current.style.transition = "transform .2s ease-out";
      elRef.current.style.transform = "translateY(0)";
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
      elRef.current.style.transition = "transform .2s ease-out";
      elRef.current.style.transform = "translateX(0)";
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
