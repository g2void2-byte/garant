import { getInitData } from "@/lib/tg";

export interface WsEvent {
  event: string;
  data?: any;
}

export interface WsHandlers {
  onEvent: (event: WsEvent) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

const MIN_BACKOFF = 1_000;
const MAX_BACKOFF = 30_000;

function buildWsUrl(initData: string): string {
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
  if (apiUrl) {
    const u = new URL(apiUrl);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = (u.pathname.replace(/\/$/, "") || "") + "/ws/notifications";
    if (initData) u.searchParams.set("initData", initData);
    return u.toString();
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const params = initData ? `?initData=${encodeURIComponent(initData)}` : "";
  return `${proto}//${window.location.host}/ws/notifications${params}`;
}

export function connectNotifications(handlers: WsHandlers): () => void {
  let socket: WebSocket | null = null;
  let backoff = MIN_BACKOFF;
  let stopped = false;
  let reconnectTimer: number | null = null;

  const open = () => {
    if (stopped) return;
    const initData = getInitData();
    if (!initData) {
      reconnectTimer = window.setTimeout(open, MAX_BACKOFF);
      return;
    }
    try {
      socket = new WebSocket(buildWsUrl(initData));
    } catch {
      scheduleReconnect();
      return;
    }
    socket.addEventListener("open", () => {
      backoff = MIN_BACKOFF;
      handlers.onOpen?.();
    });
    socket.addEventListener("message", (msg) => {
      try {
        const event: WsEvent = JSON.parse(msg.data);
        handlers.onEvent(event);
      } catch {
        /* ignore non-JSON frames */
      }
    });
    socket.addEventListener("close", () => {
      handlers.onClose?.();
      scheduleReconnect();
    });
    socket.addEventListener("error", () => {
      try {
        socket?.close();
      } catch {
        /* ignore */
      }
    });
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    reconnectTimer = window.setTimeout(open, backoff);
    backoff = Math.min(backoff * 2, MAX_BACKOFF);
  };

  open();

  return () => {
    stopped = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    try {
      socket?.close();
    } catch {
      /* ignore */
    }
  };
}
