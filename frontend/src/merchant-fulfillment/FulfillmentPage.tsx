import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  API_BASE_URL,
  api,
  useApiRead,
  type ApiComponents,
  envelope,
  formatCents,
  formatDateTime,
  honestyKinds,
  HonestyLabels,
  Icon,
  Notice,
  productName,
  shortId,
  StatusPill,
  statusStyle,
} from "../shared";

import "./fulfillment.css";

type BidView = ApiComponents["schemas"]["BidView"];
type LotProgress = ApiComponents["schemas"]["LotProgress"];
type FulfillmentRow = ApiComponents["schemas"]["FulfillmentRow"];
type ShipmentResult = ApiComponents["schemas"]["ShipmentResult"];
type Verification = ApiComponents["schemas"]["VerificationResponse"];
type Manifest = ApiComponents["schemas"]["VerificationManifest"];

/** A lot this merchant won, with the progress the API published for it. */
type AwardedLot = {
  lotId: string;
  productKey: string | null;
  progress: LotProgress | null;
};

type Problem = { code: string; message: string };
type NoticeState = { kind: "info" | "warn" | "error"; text: string; code?: string };
type Busy = "csv" | "manifest" | "verify" | "ship" | null;
type ShipmentDraft = { carrier: string; tracking_number: string };

/** service.py: only these lot statuses expose addresses and shipments (I4, FR-IG-08). */
const FUNDED_STATUSES = new Set(["FUNDED", "CLOSED"]);
/** api.md: the shipments request carries at most this many rows. */
const MAX_SHIPMENTS = 100;

/** The tracker status is the provider's own answer; absence is never "submitted". */
function trackerText(status: string | null | undefined): string {
  if (!status || status === "SKIPPED") return "tracker not submitted";
  if (status === "SUBMITTED") return "PayPal tracker submitted";
  if (status === "FAILED") return "PayPal tracker submission failed";
  return `tracker ${status.toLowerCase()}`;
}

/** Browser-side file save: the bytes are the server's, never rebuilt here. */
function saveFile(content: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function responseProblem(response: Response): Promise<Problem> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    return {
      code: body.error?.code ?? "REQUEST_FAILED",
      message: body.error?.message ?? "The request could not be completed.",
    };
  } catch {
    return { code: "REQUEST_FAILED", message: "The request could not be completed." };
  }
}

export function FulfillmentPage() {
  const bidsRead = useApiRead("/api/v1/merchant/bids", (signal) => api.GET("/api/v1/merchant/bids", {signal}));
  const won = (bidsRead.data?.items ?? []).filter((bid) => bid.status === "AWARDED");
  const wonKey = won.map((bid) => bid.lot_id).sort().join(",");
  const awardedRead = useApiRead(`/merchant/awarded-lots/${wonKey}`, async (signal) => {
    const lots = await Promise.all(won.map(async (bid: BidView): Promise<AwardedLot> => {
      let progress: LotProgress | null = null;
      try {
        const read = await api.GET("/api/v1/merchant/lots/{lot_id}/progress", {signal, params: {path: {lot_id: bid.lot_id}}});
        progress = read.data ?? null;
      } catch { /* A failed progress read keeps the awarded lot visible with unknown status. */ }
      return {lotId: bid.lot_id, productKey: typeof bid.structured?.product_key === "string" ? bid.structured.product_key : null, progress};
    }));
    return {data: lots};
  }, {enabled: Boolean(bidsRead.data)});
  const lots = awardedRead.data ?? null;
  const lotsProblem = bidsRead.error || awardedRead.error ? envelope(bidsRead.error ?? awardedRead.error) : null;
  const refreshLots = () => { void bidsRead.refetch({cancelRefetch: false}); void awardedRead.refetch({cancelRefetch: false}); };
  const [selected, setSelected] = useState<string | null>(null);

  const [rows, setRows] = useState<FulfillmentRow[] | null>(null);
  const [rowsProblem, setRowsProblem] = useState<Problem | null>(null);
  const [rowsAttempt, setRowsAttempt] = useState(0);

  const [chosen, setChosen] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ShipmentDraft>>({});
  const [shipments, setShipments] = useState<Record<string, ShipmentResult>>({});
  const [confirmShip, setConfirmShip] = useState(false);

  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);

  useEffect(() => {
    if (!lots) return;
    setSelected((current) => {
      if (current && lots.some((lot) => lot.lotId === current)) return current;
      const funded = lots.find((lot) => lot.progress && FUNDED_STATUSES.has(lot.progress.status));
      return (funded ?? lots[0])?.lotId ?? null;
    });
  }, [lots]);

  // One lot's shipping rows. A LOT_NOT_FUNDED answer keeps the lot and its status visible.
  useEffect(() => {
    if (!selected) {
      setRows(null);
      setRowsProblem(null);
      return;
    }
    let live = true;
    setRows(null);
    setRowsProblem(null);
    setChosen([]);
    setDrafts({});
    setShipments({});
    setConfirmShip(false);
    setVerification(null);
    setManifest(null);
    setNotice(null);
    void api
      .GET("/api/v1/merchant/lots/{lot_id}/fulfillment", {
        params: { path: { lot_id: selected } },
      })
      .then(({ data, error: failure }) => {
        if (!live) return;
        if (failure || !data) setRowsProblem(envelope(failure));
        else setRows(data);
      })
      .catch(() => {
        if (live) {
          setRowsProblem({
            code: "REQUEST_FAILED",
            message: "Check your connection, then reload this lot's shipping rows.",
          });
        }
      });
    return () => {
      live = false;
    };
  }, [selected, rowsAttempt]);

  const awarded = lots ?? [];
  const selectedLot = awarded.find((lot) => lot.lotId === selected) ?? null;
  const lotStatus = selectedLot?.progress?.status ?? null;
  const lotLabels = honestyKinds(selectedLot?.progress?.labels);
  const chosenRows = (rows ?? []).filter((row) => chosen.includes(row.buyer_order_id));
  const overBatch = chosenRows.length > MAX_SHIPMENTS;

  function reload(): void {
    refreshLots();
    setRowsAttempt((value) => value + 1);
  }

  function toggleChosen(orderId: string): void {
    setConfirmShip(false);
    setChosen((current) =>
      current.includes(orderId)
        ? current.filter((id) => id !== orderId)
        : [...current, orderId],
    );
  }

  function draftFor(orderId: string): ShipmentDraft {
    return drafts[orderId] ?? { carrier: "", tracking_number: "" };
  }

  function setDraft(orderId: string, field: keyof ShipmentDraft, value: string): void {
    setDrafts((current) => ({
      ...current,
      [orderId]: { ...draftFor(orderId), [field]: value },
    }));
  }

  async function downloadCsv(): Promise<void> {
    if (!selected || busy) return;
    setBusy("csv");
    setNotice(null);
    try {
      // The CSV is the API's own rendering of the same rows, so it is fetched,
      // never rebuilt from the JSON in the browser.
      const response = await fetch(
        `${API_BASE_URL}/api/v1/merchant/lots/${selected}/fulfillment`,
        { credentials: "include", headers: { Accept: "text/csv" } },
      );
      if (!response.ok) {
        const problem = await responseProblem(response);
        setNotice({ kind: "error", code: problem.code, text: problem.message });
        return;
      }
      saveFile(await response.text(), `fulfillment-${selected}.csv`, "text/csv;charset=utf-8");
      setNotice({
        kind: "info",
        text: "Shipping CSV downloaded. It carries buyer names and addresses; share it only with your shipping tool.",
      });
    } catch {
      setNotice({
        kind: "error",
        code: "REQUEST_FAILED",
        text: "The CSV could not be downloaded. Check your connection and try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function downloadManifest(): Promise<void> {
    if (!selected || busy) return;
    setBusy("manifest");
    setNotice(null);
    try {
      const { data, error: failure } = await api.GET(
        "/api/v1/merchant/lots/{lot_id}/verification-manifest",
        { params: { path: { lot_id: selected } } },
      );
      if (failure || !data) {
        const problem = envelope(failure);
        setNotice({ kind: "error", code: problem.code, text: problem.message });
        return;
      }
      setManifest(data);
      saveFile(
        JSON.stringify(data, null, 2),
        `verification-manifest-${selected}.json`,
        "application/json",
      );
      setNotice({
        kind: "info",
        text: `Verification manifest downloaded: ${data.items.length} captured ${
          data.items.length === 1 ? "order" : "orders"
        }, ${formatCents(data.expected_captured_total_cents)} ${data.currency} expected.`,
      });
    } catch {
      setNotice({
        kind: "error",
        code: "REQUEST_FAILED",
        text: "The verification manifest could not be downloaded. Check your connection and try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function verifyPayments(): Promise<void> {
    if (!selected || busy) return;
    setBusy("verify");
    setNotice(null);
    setVerification(null);
    try {
      const { data, error: failure } = await api.GET(
        "/api/v1/merchant/lots/{lot_id}/verification",
        { params: { path: { lot_id: selected } } },
      );
      if (failure || !data) {
        const problem = envelope(failure);
        setNotice({
          kind: "error",
          code: problem.code,
          text:
            problem.code === "RATE_LIMITED"
              ? "Verification is limited to 10 live checks a minute. Try again in a minute."
              : problem.message,
        });
        return;
      }
      setVerification(data);
    } catch {
      setNotice({
        kind: "error",
        code: "REQUEST_FAILED",
        text: "PayPal verification could not run. Check your connection and try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  function shipmentPayload(): { buyer_order_id: string; carrier: string; tracking_number: string }[] {
    return chosenRows.map((row) => {
      const draft = draftFor(row.buyer_order_id);
      return {
        buyer_order_id: row.buyer_order_id,
        carrier: draft.carrier.trim(),
        tracking_number: draft.tracking_number.trim(),
      };
    });
  }

  /** A tracker write is external and irreversible from here, so it needs a second click. */
  function requestShipments(): void {
    if (!selected || busy || chosenRows.length === 0) return;
    if (overBatch) {
      setNotice({
        kind: "warn",
        text: `The API records at most ${MAX_SHIPMENTS} shipments per request. Select ${MAX_SHIPMENTS} or fewer orders.`,
      });
      return;
    }
    if (shipmentPayload().some((item) => !item.carrier || !item.tracking_number)) {
      setNotice({
        kind: "warn",
        text: "Every selected order needs its own carrier and tracking number before it can be marked shipped.",
      });
      return;
    }
    setNotice(null);
    setConfirmShip(true);
  }

  async function recordShipments(): Promise<void> {
    if (!selected || busy || chosenRows.length === 0 || !confirmShip) return;
    const shipmentsToSend = shipmentPayload();
    setBusy("ship");
    setNotice(null);
    try {
      const { data, error: failure } = await api.POST(
        "/api/v1/merchant/lots/{lot_id}/shipments",
        {
          params: { path: { lot_id: selected } },
          body: { shipments: shipmentsToSend },
        },
      );
      if (failure || !data) {
        const problem = envelope(failure);
        setNotice({ kind: "error", code: problem.code, text: problem.message });
        return;
      }
      setShipments((current) => {
        const next = { ...current };
        for (const row of data.rows) next[row.buyer_order_id] = row;
        return next;
      });
      setChosen([]);
      setDrafts({});
      setConfirmShip(false);
      const refused = data.rows.filter((row) => row.status !== "RECORDED").length;
      setNotice({
        kind: refused > 0 ? "warn" : "info",
        text:
          refused > 0
            ? `${data.accepted} of ${data.rows.length} shipments recorded; ${refused} ${
                refused === 1 ? "row was" : "rows were"
              } refused. The status column below is the API's answer for each row.`
            : `${data.accepted} of ${data.rows.length} shipments recorded. Each row below shows the PayPal tracker answer.`,
      });
    } catch {
      setNotice({
        kind: "error",
        code: "REQUEST_FAILED",
        text: "Shipments could not be recorded. Check your connection and try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="merchant-page">
      <header className="merchant-heading">
        <div>
          <h1 className="shop-title">Fulfillment</h1>
          <p className="shop-copy mt-2">
            Shipping rows, the CSV, shipments and the verification manifest open after a lot is
            funded. Addresses come from buyers’ captured orders and are shown here only.
          </p>
        </div>
        <button type="button" className="shop-quiet-button" onClick={reload}>
          <Icon name="returns" />
          Refresh
        </button>
      </header>

      {notice ? (
        notice.code ? (
          <Notice kind={notice.kind} code={notice.code}>
            {notice.text}
          </Notice>
        ) : (
          <Notice kind={notice.kind}>{notice.text}</Notice>
        )
      ) : null}

      <section className="shop-panel shop-panel-pad ff-picker" aria-labelledby="ff-lots-title">
        <h2 id="ff-lots-title">Awarded lots</h2>
        {lots === null && !lotsProblem ? (
          <p className="shop-copy mt-2" role="status">
            Loading the lots awarded to your merchant account.
          </p>
        ) : lotsProblem ? (
          <div className="mt-3">
            <Notice kind="error" code={lotsProblem.code}>
              {lotsProblem.message}{" "}
              <button
                type="button"
                className="merchant-link"
                onClick={() => refreshLots()}
              >
                Reload awarded lots
              </button>
            </Notice>
          </div>
        ) : awarded.length === 0 ? (
          <div className="mt-3">
            <p className="shop-copy">
              No awarded lots yet. A lot appears here after your bid wins it.
            </p>
            <Link className="button-secondary mt-4" to="/merchant/bids">
              Open Active Bids
              <Icon name="arrow" />
            </Link>
          </div>
        ) : (
          <>
            <label className="mt-3 block text-sm font-semibold">
              Awarded lot
              <select
                className="form-input ff-select"
                value={selected ?? ""}
                onChange={(event) => setSelected(event.target.value)}
              >
                {awarded.map((lot) => (
                  <option key={lot.lotId} value={lot.lotId}>
                    {productName(lot.productKey)} · {shortId(lot.lotId)} ·{" "}
                    {lot.progress?.status ?? "status unavailable"}
                  </option>
                ))}
              </select>
            </label>
            <p className="merchant-help">
              Only lots awarded to your merchant account are listed. A lot’s status is the database
              lot status; fulfillment opens at FUNDED or CLOSED.
            </p>
            {lotLabels.length > 0 ? (
              <div className="mt-3">
                <HonestyLabels kinds={lotLabels} />
              </div>
            ) : null}
          </>
        )}
      </section>

      {selected ? (
        rowsProblem?.code === "LOT_NOT_FUNDED" ? (
          <section className="shop-panel shop-panel-pad" aria-labelledby="ff-not-funded">
            <h2 id="ff-not-funded">Not funded yet</h2>
            <p className="shop-copy mt-2">
              Shipping rows, the CSV, shipments and the manifest stay closed until the lot is
              funded or closed. The API answered LOT_NOT_FUNDED for this lot.
            </p>
            <dl className="merchant-facts">
              <div>
                <dt>Lot status</dt>
                <dd>
                  {lotStatus ? (
                    <>
                      <StatusPill status={lotStatus} tone={statusStyle(lotStatus).tone}>
                        {statusStyle(lotStatus).label}
                      </StatusPill>{" "}
                      <code className="merchant-code">{lotStatus}</code>
                    </>
                  ) : (
                    "Not available"
                  )}
                </dd>
              </div>
              <div>
                <dt>Lot</dt>
                <dd>
                  <code className="merchant-code">{selected}</code>
                </dd>
              </div>
            </dl>
            <button
              type="button"
              className="shop-quiet-button mt-4"
              onClick={() => setRowsAttempt((value) => value + 1)}
            >
              <Icon name="returns" />
              Check again
            </button>
          </section>
        ) : rowsProblem ? (
          <Notice kind="error" code={rowsProblem.code}>
            {rowsProblem.message}{" "}
            <button
              type="button"
              className="merchant-link"
              onClick={() => setRowsAttempt((value) => value + 1)}
            >
              Reload shipping rows
            </button>
          </Notice>
        ) : rows === null ? (
          <div role="status" aria-busy="true" aria-label="Loading shipping rows">
            <div className="shop-panel shop-panel-pad">
              <div className="skeleton h-5 w-1/3" />
              <div className="skeleton mt-3 h-4 w-2/3" />
              <div className="skeleton mt-3 h-4 w-1/2" />
            </div>
          </div>
        ) : (
          <>
            <nav className="ff-task-navigation" aria-label="Fulfillment tasks"><a href="#ff-rows-title">Shipping queue</a><a href="#ff-verify-title">Payment verification</a></nav>
            <section className="shop-panel shop-panel-pad" aria-labelledby="ff-rows-title">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 id="ff-rows-title">Captured orders</h2>
                  <p className="shop-copy mt-1">
                    {rows.length} {rows.length === 1 ? "order" : "orders"} with a completed PayPal
                    capture in this lot. Mark them shipped with the carrier and tracking number you
                    sent.
                  </p>
                </div>
                <p className="ff-total text-sm text-muted">
                  {formatCents(rows.reduce((sum, row) => sum + row.total_cents, 0))} USD captured
                </p>
              </div>

              <div className="ff-toolbar">
                <button
                  type="button"
                  className="button-secondary"
                  disabled={busy !== null}
                  onClick={() => void downloadCsv()}
                >
                  <Icon name="truck" />
                  {busy === "csv" ? "Preparing CSV…" : "Shipping CSV"}
                </button>
                <span className="merchant-help">
                  The CSV is the API’s own file. Names and addresses are in it, so download it only
                  where those may be handled.
                </span>
              </div>

              {rows.length === 0 ? (
                <p className="merchant-empty mt-4">
                  No captured orders yet. A shipping row appears after PayPal confirms a capture in
                  this lot.
                </p>
              ) : (
                <div className="ff-table-wrap">
                  <p className="merchant-help">
                    Shipment results appear beside an order after you mark it here; the API does
                    not return earlier shipments.
                  </p>
                  <table className="ff-table">
                    <caption className="sr-only">Captured orders in this lot</caption>
                    <thead>
                      <tr>
                        <th scope="col">Include</th>
                        <th scope="col">Buyer order</th>
                        <th scope="col">Ship to</th>
                        <th scope="col">Amounts</th>
                        <th scope="col">Total</th>
                        <th scope="col">PayPal capture</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <ShippingRow
                          key={row.buyer_order_id}
                          row={row}
                          checked={chosen.includes(row.buyer_order_id)}
                          shipment={shipments[row.buyer_order_id] ?? null}
                          onToggle={() => toggleChosen(row.buyer_order_id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {chosenRows.length > 0 ? (
                <section className="ff-ship" aria-labelledby="ff-ship-title">
                  <h3 id="ff-ship-title">
                    Mark {chosenRows.length} selected{" "}
                    {chosenRows.length === 1 ? "order" : "orders"} as shipped
                  </h3>
                  <p className="merchant-help">
                    Each order needs its own carrier and tracking number. Up to {MAX_SHIPMENTS}{" "}
                    orders per request.
                  </p>
                  {overBatch ? (
                    <p className="ff-mismatch" role="alert">
                      {chosenRows.length} orders are selected. The API records at most{" "}
                      {MAX_SHIPMENTS} per request; deselect {chosenRows.length - MAX_SHIPMENTS} or
                      send this batch in two.
                    </p>
                  ) : null}
                  <ul className="ff-ship-list">
                    {chosenRows.map((row) => (
                      <li key={row.buyer_order_id} className="ff-ship-row">
                        <p>
                          <code className="merchant-code">{row.buyer_order_id}</code>
                        </p>
                        <label>
                          Carrier
                          <input
                            className="form-input"
                            type="text"
                            autoComplete="off"
                            aria-label={`Carrier for ${row.buyer_order_id}`}
                            value={draftFor(row.buyer_order_id).carrier}
                            onChange={(event) =>
                              setDraft(row.buyer_order_id, "carrier", event.target.value)
                            }
                          />
                        </label>
                        <label>
                          Tracking number
                          <input
                            className="form-input"
                            type="text"
                            autoComplete="off"
                            aria-label={`Tracking number for ${row.buyer_order_id}`}
                            value={draftFor(row.buyer_order_id).tracking_number}
                            onChange={(event) =>
                              setDraft(row.buyer_order_id, "tracking_number", event.target.value)
                            }
                          />
                        </label>
                      </li>
                    ))}
                  </ul>
                  <div className="merchant-actions">
                    {confirmShip ? (
                      <>
                        <button
                          type="button"
                          className="button-primary"
                          disabled={busy !== null}
                          onClick={() => void recordShipments()}
                        >
                          <Icon name="truck" />
                          {busy === "ship"
                            ? "Recording…"
                            : `Confirm ${chosenRows.length} ${
                                chosenRows.length === 1 ? "shipment" : "shipments"
                              } with PayPal`}
                        </button>
                        <button
                          type="button"
                          className="shop-quiet-button"
                          disabled={busy !== null}
                          onClick={() => setConfirmShip(false)}
                        >
                          Keep editing
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="button-primary"
                          disabled={busy !== null || overBatch}
                          onClick={requestShipments}
                        >
                          <Icon name="truck" />
                          Record shipments
                        </button>
                        <button
                          type="button"
                          className="shop-quiet-button"
                          disabled={busy !== null}
                          onClick={() => {
                            setChosen([]);
                            setDrafts({});
                            setConfirmShip(false);
                          }}
                        >
                          Clear selection
                        </button>
                      </>
                    )}
                  </div>
                  {confirmShip ? (
                    <p className="merchant-help" role="status">
                      Recording writes a PayPal tracker entry for each selected order. Nothing is
                      sent until you confirm.
                    </p>
                  ) : null}
                </section>
              ) : null}
            </section>

            <section className="shop-panel shop-panel-pad" aria-labelledby="ff-verify-title">
              <h2 id="ff-verify-title">Verify the money</h2>
              <p className="shop-copy mt-1">
                The manifest lists the PayPal order and capture IDs, amounts and capture times; it
                carries no buyer names or addresses. Verification runs a live read of every order
                on PayPal and changes nothing.
              </p>
              <div className="ff-toolbar">
                <button
                  type="button"
                  className="button-secondary"
                  disabled={busy !== null}
                  onClick={() => void downloadManifest()}
                >
                  <Icon name="receipt" />
                  {busy === "manifest" ? "Preparing manifest…" : "Verification manifest"}
                </button>
                <button
                  type="button"
                  className="button-secondary"
                  disabled={busy !== null}
                  onClick={() => void verifyPayments()}
                >
                  <Icon name="shield" />
                  {busy === "verify" ? "Checking with PayPal…" : "Verify payments"}
                </button>
              </div>
              <p className="merchant-help">
                Verification makes live PayPal reads and is limited to 10 checks a minute.
              </p>

              {manifest ? (
                <div className="ff-verify-result">
                  <h3>
                    Manifest: {manifest.items.length} captured{" "}
                    {manifest.items.length === 1 ? "order" : "orders"},{" "}
                    {formatCents(manifest.expected_captured_total_cents)} {manifest.currency}{" "}
                    expected
                  </h3>
                  <p className="merchant-help">{manifest.how_to_verify}</p>
                </div>
              ) : null}

              {verification ? (
                <div className="ff-verify-result" aria-live="polite">
                  <h3>
                    {verification.all_match
                      ? `All ${verification.total} captures match PayPal`
                      : `${verification.matched} of ${verification.total} captures match PayPal`}
                  </h3>
                  <p className="merchant-help">
                    Checked {formatDateTime(verification.checked_at)} with a live read of every
                    order from PayPal. This check only reads; it moves no money.
                  </p>
                  <dl className="ff-totals">
                    <div>
                      <dt>Expected captured total</dt>
                      <dd>{formatCents(verification.expected_captured_total_cents)} USD</dd>
                    </div>
                    <div>
                      <dt>PayPal captured total</dt>
                      <dd>{formatCents(verification.paypal_captured_total_cents)} USD</dd>
                    </div>
                  </dl>
                  {verification.all_match ? null : (
                    <p className="ff-mismatch" role="alert">
                      PayPal’s answer differs from what this lot recorded. Check the mismatched rows
                      below before shipping.
                    </p>
                  )}
                  <ul className="ff-items" aria-label="Captures checked with PayPal">
                    {verification.items.map((item) => (
                      <li key={`${item.paypal_order_id}-${item.paypal_capture_id}`}>
                        <span
                          className={`ff-flag ${item.match ? "ff-flag-good" : "ff-flag-bad"}`}
                        >
                          {item.match ? "Matches" : "Does not match"}
                        </span>
                        <span>
                          Order <code>{item.paypal_order_id}</code> · capture{" "}
                          <code>{item.paypal_capture_id}</code>
                        </span>
                        <span>
                          PayPal {item.paypal_capture_status} at{" "}
                          {formatCents(item.paypal_amount_cents)}; expected{" "}
                          {formatCents(item.expected_amount_cents)}.
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          </>
        )
      ) : null}
    </div>
  );
}

/** One shipping row. The address is rendered where the API returned it, never stored. */
function ShippingRow({
  row,
  checked,
  shipment,
  onToggle,
}: {
  row: FulfillmentRow;
  checked: boolean;
  shipment: ShipmentResult | null;
  onToggle: () => void;
}) {
  return (
    <tr>
      <td data-label="Include">
        <label className="ff-check">
          <input
            type="checkbox"
            checked={checked}
            onChange={onToggle}
            aria-label={`Select order ${row.buyer_order_id}`}
          />
        </label>
      </td>
      <td data-label="Buyer order">
        <code className="merchant-code">{row.buyer_order_id}</code>
        {shipment ? (
          <span className="ff-ship-result" role="status">
            <strong>{shipment.status === "RECORDED" ? "Shipment recorded" : "Not recorded"}</strong>{" "}
            · status <code>{shipment.status}</code> · {trackerText(shipment.paypal_tracker_status)}
          </span>
        ) : null}
      </td>
      <td data-label="Ship to">
        <span className="ff-address">
          <strong>{row.name}</strong>
          <span>{row.line1}</span>
          {row.line2 ? <span>{row.line2}</span> : null}
          <span>
            {row.city}, {row.region} {row.postal_code}
          </span>
          <span>{row.country_code}</span>
        </span>
      </td>
      <td data-label="Amounts">
        <span className="ff-money">
          <span>Item {formatCents(row.item_cents)}</span>
          <span>Shipping {formatCents(row.shipping_cents)}</span>
          <span>Tax {formatCents(row.tax_cents)}</span>
        </span>
      </td>
      <td data-label="Total">
        <span className="ff-total">{formatCents(row.total_cents)}</span>{" "}
        <span className="text-xs text-muted">USD</span>
      </td>
      <td data-label="PayPal capture">
        <code className="merchant-code">{row.paypal_capture_id}</code>
      </td>
    </tr>
  );
}
