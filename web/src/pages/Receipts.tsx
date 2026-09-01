import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { STATUS_LABELS, date, ft } from "../lib/format";
import { AsyncBlock, Card, useAsync } from "../components/ui";

const FILTERS = [
  { value: "", label: "Mind" },
  { value: "needs_review", label: "Ellenőrzendő" },
  { value: "parsed", label: "Feldolgozva" },
  { value: "confirmed", label: "Megerősítve" },
  { value: "pending", label: "Sorban áll" },
  { value: "failed", label: "Sikertelen" },
];

export default function Receipts() {
  const [status, setStatus] = useState("");
  const state = useAsync(() => api.receipts({ status: status || undefined, limit: 200 }), [status]);

  return (
    <>
      <h1 style={{ marginBottom: 14 }}>Blokkok</h1>

      <div className="row" style={{ marginBottom: 14 }}>
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            className="btn"
            aria-pressed={status === filter.value}
            style={
              status === filter.value
                ? { borderColor: "var(--series-1)", color: "var(--series-1)", fontWeight: 650 }
                : undefined
            }
            onClick={() => setStatus(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      <Card>
        <AsyncBlock state={state} empty="Még nincs blokk ebben a nézetben.">
          {(receipts) => (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Dátum</th>
                    <th>Bolt</th>
                    <th className="num">Összeg</th>
                    <th className="num">Tétel</th>
                    <th>Állapot</th>
                  </tr>
                </thead>
                <tbody>
                  {receipts.map((receipt) => (
                    <tr key={receipt.id}>
                      <td className="mono">
                        <Link to={`/blokkok/${receipt.id}`}>
                          {date(receipt.purchased_at ?? receipt.created_at)}
                        </Link>
                      </td>
                      <td>{receipt.merchant_name ?? <span className="muted">ismeretlen</span>}</td>
                      <td className="num">{ft(receipt.total_gross)}</td>
                      <td className="num">{receipt.item_count}</td>
                      <td>
                        <span
                          className={
                            receipt.status === "needs_review" ? "badge warn"
                              : receipt.status === "failed" ? "badge bad"
                              : receipt.status === "confirmed" ? "badge good"
                              : "badge"
                          }
                        >
                          {STATUS_LABELS[receipt.status] ?? receipt.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </Card>
    </>
  );
}
