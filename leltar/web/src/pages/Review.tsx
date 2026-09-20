import { useEffect, useState } from "react";

import { api, type Photo } from "../lib/api";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";
import { PHOTO_STATUS, REVIEW_REASONS, dateTime } from "../lib/format";
import { Link } from "react-router-dom";

/** The queue: photographs whose guesses nobody has looked at yet.
 *
 *  It refreshes itself while anything is still being read, because the normal use is to
 *  photograph a shelf and then wait ten seconds on this screen.
 */
export default function Review() {
  const [nonce, setNonce] = useState(0);
  const photos = useAsync(() => api.photos({ limit: 100 }), [nonce]);

  const waiting = (photos.data ?? []).some(
    (photo) => photo.status === "pending" || photo.status === "processing",
  );

  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setNonce((value) => value + 1), 4000);
    return () => clearInterval(timer);
  }, [waiting]);

  const pending = (photos.data ?? []).filter((photo) => photo.status !== "reviewed");
  const done = (photos.data ?? []).filter((photo) => photo.status === "reviewed");

  return (
    <>
      <Card
        title="Ellenőrzésre vár"
        note={waiting ? "olvasás folyamatban…" : undefined}
        action={
          <button className="btn" onClick={() => setNonce((value) => value + 1)}>
            Frissítés
          </button>
        }
      >
        <AsyncBlock state={photos} empty="Még nincs feltöltött fénykép.">
          {() =>
            pending.length === 0 ? (
              <Empty>Minden fényképet átnéztél. 👌</Empty>
            ) : (
              pending.map((photo) => <Row key={photo.id} photo={photo} />)
            )
          }
        </AsyncBlock>
      </Card>

      {done.length > 0 && (
        <Card title="Átnézett fényképek" note={`${done.length} db`}>
          {done.slice(0, 20).map((photo) => <Row key={photo.id} photo={photo} />)}
        </Card>
      )}
    </>
  );
}

function Row({ photo }: { photo: Photo }) {
  const reasons = photo.review_reasons ?? [];
  return (
    <div className="list-row">
      <Link to={`/fenykep/${photo.id}`} className="grow" style={{ textDecoration: "none" }}>
        <div className="name">{photo.scene ?? "Fénykép"}</div>
        <div className="where">
          {photo.place_path ?? "hely nélkül"} · {dateTime(photo.taken_at ?? photo.created_at)}
        </div>
        {photo.error && <div className="error">{photo.error}</div>}
        {reasons.length > 0 && (
          <div className="draft-meta">
            {reasons.map((reason) => (
              <span className="reason" key={reason}>{REVIEW_REASONS[reason] ?? reason}</span>
            ))}
          </div>
        )}
      </Link>
      <div style={{ textAlign: "right" }}>
        <span className={badgeClass(photo.status)}>{PHOTO_STATUS[photo.status] ?? photo.status}</span>
        <div className="where">
          {photo.draft_count > 0
            ? `${photo.draft_count} javaslat`
            : `${photo.item_count} tétel`}
        </div>
      </div>
    </div>
  );
}

function badgeClass(status: string): string {
  if (status === "failed") return "badge bad";
  if (status === "needs_review") return "badge warn";
  if (status === "reviewed") return "badge good";
  return "badge";
}
