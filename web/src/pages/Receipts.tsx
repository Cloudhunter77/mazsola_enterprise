import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type ReceiptSummary } from "../lib/api";
import { STATUS_LABELS, ft, shortDate } from "../lib/format";
import { groupByMonth } from "../lib/group";
import { AsyncBlock, Card, MonthHeading, useAsync, useLive } from "../components/ui";

const FILTERS = [
  { value: "", label: "Mind" },
  { value: "needs_review", label: "Ellenőrzendő" },
  { value: "parsed", label: "Feldolgozva" },
  { value: "confirmed", label: "Megerősítve" },
  { value: "pending", label: "Sorban áll" },
  { value: "failed", label: "Sikertelen" },
];

const BADGE: Record<string, string> = {
  needs_review: "badge warn",
  failed: "badge bad",
};

export default function Receipts() {
  const [status, setStatus] = useState("");
  const state = useAsync(() => api.receipts({ status: status || undefined, limit: 200 }), [status]);
  // A receipt uploaded from the phone shows up as queued and turns into a result by itself.
  useLive(state, (rows) => rows.some((row) => row.status === "pending" || row.status === "processing"));

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Blokkok</h1>

      <div className="row" style={{ marginBottom: 14, gap: 8 }}>
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            className="btn"
            aria-pressed={status === filter.value}
            onClick={() => setStatus(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <Card>
        <AsyncBlock state={state} empty="Még nincs blokk ebben a nézetben.">
          {/* The ones with no date yet - still in the queue, or not readable - come first:
              they are the newest, and the ones that may need you. */}
          {(receipts) => groupByMonth(receipts, (r) => r.purchased_at).map((group) => (
            <section key={group.key} className="list-section">
              <MonthHeading count={group.items.length}
                            total={group.items.reduce((sum, r) => sum + Number(r.total_gross ?? 0), 0)}>
                {group.label}
              </MonthHeading>
              <ul className="rows">
                {group.items.map((receipt) => (
                  <li key={receipt.id}>
                    <ReceiptRow receipt={receipt} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </AsyncBlock>
      </Card>
    </>
  );
}

function ReceiptRow({ receipt }: { receipt: ReceiptSummary }) {
  const inFlight = receipt.status === "pending" || receipt.status === "processing";
  const name =
    receipt.merchant_name ?? (inFlight ? "Felismerés…" : "Ismeretlen bolt");

  const details = [
    receipt.purchased_at
      ? shortDate(receipt.purchased_at)
      : `feltöltve ${shortDate(receipt.created_at)}`,
    receipt.item_count > 0 ? `${receipt.item_count} tétel` : null,
    // Made by a monthly item rather than by you: worth saying, or it looks like a mystery.
    receipt.source === "recurring" ? "↻ rendszeres" : null,
  ].filter(Boolean);

  return (
    <Link className="list-row" to={`/blokkok/${receipt.id}`}>
      <span className={receipt.merchant_name ? "title" : "title muted"}>{name}</span>
      <span className="amount">{receipt.total_gross == null ? "–" : ft(receipt.total_gross)}</span>
      <span className="meta">{details.join(" · ")}</span>
      {/* Confirmed is the normal state - a badge on every row would be noise. */}
      {receipt.status !== "confirmed" && (
        <span className="side">
          <span className={BADGE[receipt.status] ?? "badge"}>
            {inFlight && <span className="spinner" style={{ width: 10, height: 10 }} aria-hidden />}
            {STATUS_LABELS[receipt.status] ?? receipt.status}
          </span>
        </span>
      )}
    </Link>
  );
}
