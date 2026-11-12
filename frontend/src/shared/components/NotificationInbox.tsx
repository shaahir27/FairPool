import { useEffect, useId, useRef, useState } from "react";

import { api } from "../api/client";
import { getCsrfToken } from "../lib/csrf";
import { formatDateTime } from "../lib/format";
import { Icon } from "./Icon";
import "./NotificationInbox.css";

interface NotificationItem {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

function reasonOf(payload: Record<string, unknown>): string | null {
  return typeof payload.reason === "string" && payload.reason.trim() ? payload.reason : null;
}

/**
 * One sentence per stored kind (FR-UI-09). The inbox reuses the copy the sites that
 * write the row already use, and never decides an outcome: a flagged bid is "not
 * rejected" until the deterministic rules and the merchant say otherwise (rule 5).
 * Kinds this build does not know fall back to one neutral line rather than raw JSON.
 */
function describeNotification(kind: string, payload: Record<string, unknown>): string {
  switch (kind) {
    case "demand.pool_proposed":
      return `A pool for ${typeof payload.title === "string" ? payload.title : "a product you follow"} was proposed. An operator will review it before publication.`;
    case "demand.pool_open":
      return `A pool for ${typeof payload.title === "string" ? payload.title : "a product you follow"} was published. Check Interests in My Pools for its opening and join separately.`;
    case "lot.awarded":
      return "Your bid won a lot. Checkout opens when the pool reaches its award step.";
    case "lot.cancelled":
      return "A lot you were part of was cancelled before checkout started.";
    case "lot.funded": {
      const captures = payload.completed_captures;
      return typeof captures === "number"
        ? `Your lot reached its minimum with ${captures} buyer${captures === 1 ? "" : "s"} paid.`
        : "Your lot reached its minimum buyer count and is funded.";
    }
    case "lot.closed":
      return "Your lot's checkout window closed.";
    case "bid.lost":
      return "Your bid was not selected for a lot.";
    case "bid.rejected": {
      const reason = reasonOf(payload);
      return reason ? `Your bid was not accepted: ${reason}` : "Your bid was not accepted.";
    }
    case "bid.flagged":
      return "Your bid was flagged for a manual check. It has not been rejected.";
    case "entry.rejected": {
      const reason = reasonOf(payload);
      return reason
        ? `Your pool entry was not accepted (${reason}).`
        : "Your pool entry was not accepted.";
    }
    case "buyer_order.offered":
      return "An offer is waiting for you in My Pools.";
    case "buyer_order.rejected":
      return "An offer could not go ahead and the seat was released.";
    case "buyer_order.capture_pending":
      return "Your payment is pending and will be checked again.";
    case "buyer_order.capture_failed":
      return "Your payment could not be completed.";
    case "buyer_order.captured":
    case "order.capture":
      return "Your payment was captured.";
    case "buyer_order.voided":
      return "The payment hold on your offer was released.";
    case "buyer_order.refunding":
      return "A refund for your payment is in progress.";
    case "buyer_order.refunded":
    case "refund":
      return "Your refund was completed.";
    case "order.vault_charge":
      return "Your saved payment method is being charged for an offer.";
    case "buyer_order.authorized":
      return "Your payment is authorized and will be captured when the lot funds.";
    case "buyer_order.declined":
      return "You declined an offer, so the seat was released.";
    case "buyer_order.expired":
      return "An offer expired before it was completed.";
    case "buyer_order.auth_failed":
      return "The payment hold for your offer did not go through.";
    default:
      return "You have a new notification.";
  }
}

/**
 * The in-app inbox shared by the buyer and merchant shells.
 *
 * Opening it asks the server for the caller's own newest 50 rows and then marks them
 * read, exactly as CR-13 describes. The rows stay inside the app: no email, SMS or
 * push is sent, and this component never mutates an entry, an order or a payment.
 */
export function NotificationInbox() {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [staleToken, setStaleToken] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  // The badge has to exist before the panel is opened: marking read on open would
  // otherwise destroy the only signal that anything arrived.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const { data, error } = await api.GET("/api/v1/me/notifications");
        if (live && !error && data) setUnread(data.unread);
      } catch {
        // A failed badge read is silent; opening the panel reports the error.
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const load = async () => {
    setStatus("loading");
    try {
      // The generated client sends the session cookie and CSRF header, and a 401
      // still resets the cached session the same way every other read does.
      const { data, error } = await api.GET("/api/v1/me/notifications");
      if (error || !data) throw new Error("notifications unavailable");
      setItems(data.items);
      setUnread(data.unread);
      setStatus("ready");
      // A tab opened without signing in has the cookie but no CSRF token; the rows
      // still render, and the header says why they stay unread.
      if (!getCsrfToken()) {
        setStaleToken(true);
        return;
      }
      try {
        const marked = await api.POST("/api/v1/me/notifications/read");
        if (!marked.error) {
          setUnread(0);
          setItems((rows) =>
            rows.map((row) => (row.read_at ? row : { ...row, read_at: new Date().toISOString() })),
          );
        }
      } catch {
        // Rows are already on screen; a failed mark-read only leaves the badge up.
      }
    } catch {
      setStatus("error");
    }
  };

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    void load();
  };

  return (
    <div className="inbox">
      <button
        ref={trigger}
        type="button"
        className="inbox-trigger"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
      >
        <Icon name="mail" />
        <span>Inbox</span>
        {unread > 0 ? <span className="inbox-badge">{unread}</span> : null}
      </button>
      {open ? (
        <section id={panelId} className="inbox-panel" aria-label="Notifications">
          <header className="inbox-header">
            <h2>Notifications</h2>
            <span className="inbox-state" role="status">
              {unread > 0 ? `${unread} unread` : "All read"}
            </span>
            <button
              type="button"
              className="inbox-close"
              aria-label="Close notifications"
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <Icon name="close" />
            </button>
          </header>
          {staleToken ? (
            <p className="inbox-note" role="status">
              Your sign-in token has expired in this tab, so these stay unread. Sign in
              again to clear them.
            </p>
          ) : null}
          {status === "loading" ? <p className="inbox-note">Loading notifications…</p> : null}
          {status === "error" ? (
            <p className="inbox-note" role="alert">
              Notifications could not be loaded.{" "}
              <button type="button" className="inbox-retry" onClick={() => void load()}>
                Try again
              </button>
            </p>
          ) : null}
          {status === "ready" && items.length === 0 ? (
            <p className="inbox-note">No notifications yet.</p>
          ) : null}
          {items.length > 0 ? (
            <ul className="inbox-list">
              {items.map((item) => (
                <li key={item.id} className={item.read_at ? "inbox-item" : "inbox-item is-unread"}>
                  <p>{describeNotification(item.kind, item.payload)}</p>
                  <time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
