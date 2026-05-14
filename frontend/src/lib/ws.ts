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

// Plain URL — initData no longer rides in the query string. The
// backend authenticates via the first JSON frame after ``accept()``
// (see backend/app/routers/ws.py for the matching server flow).
function buildWsUrl(): string {
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
  if (apiUrl) {
    const u = new URL(apiUrl);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = (u.pathname.replace(/\/$/, "") || "") + "/ws/notifications";
    return u.toString();
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/notifications`;
}

export function connectNotifications(handlers: WsHandlers): () => void {
  let socket: WebSocket | null = null;
  let backoff = MIN_BACKOFF;
  let stopped = false;
  let reconnectTimer: number | null = null;
  // Each new socket starts un-authed; the auth ACK from the server
  // flips this true and only *then* do we surface ``onOpen`` to the
  // caller so consumers don't optimistically treat a 4001-closed
  // socket as "connected".
  let authed = false;

  const open = () => {
    if (stopped) return;
    const initData = getInitData();
    if (!initData) {
      reconnectTimer = window.setTimeout(open, MAX_BACKOFF);
      return;
    }
    authed = false;
    try {
      socket = new WebSocket(buildWsUrl());
    } catch {
      scheduleReconnect();
      return;
    }
    socket.addEventListener("open", () => {
      // The transport is up; send auth and wait for the server ACK
      // before announcing ``onOpen`` to the caller.
      try {
        socket?.send(JSON.stringify({ type: "auth", init_data: initData }));
      } catch {
        try {
          socket?.close();
        } catch {
          /* ignore */
        }
      }
    });
    socket.addEventListener("message", (msg) => {
      let parsed: any;
      try {
        parsed = JSON.parse(msg.data);
      } catch {
        return; // ignore non-JSON frames
      }
      if (!authed) {
        // The first frame must be the auth ACK. Anything else means
        // the server changed shape or we reconnected against an old
        // build — close and let backoff retry.
        if (parsed && parsed.type === "auth" && parsed.ok === true) {
          authed = true;
          backoff = MIN_BACKOFF;
          handlers.onOpen?.();
        } else {
          try {
            socket?.close();
          } catch {
            /* ignore */
          }
        }
        return;
      }
      handlers.onEvent(parsed as WsEvent);
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
