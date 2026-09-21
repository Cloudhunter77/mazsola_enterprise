import { useEffect, useState } from "react";

import { api, type Photo } from "../lib/api";
import { AsyncBlock, Card, Empty, useAsync } from "../components/ui";
import { PHOTO_STATUS, REVIEW_REASONS, dateTime, photoTitle } from "../lib/format";
import { Link } from "react-router-dom";

/** The queue: photographs whose guesses nobody has looked at yet.
 *
 *  This screen is half of a two-person job - one person walks the house photographing,
 *  the other sits here approving names - so it refreshes itself the whole time it is
 *  open, not only while something it already knows about is being read. Waiting for the
 *  reviewer to press a button before they can see the photographer's work is what would
 *  make the pair worse than one person doing both.
 *
 *  Polling, not a live connection: two people on a home NAS, and a request every few
 *  seconds costs less than a socket that has to survive a phone locking itself.
 */
const POLL_BUSY_MS = 3000;   // something is mid-read; the answer is seconds away
const POLL_IDLE_MS = 6000;   // just watching for the other person's next photograph

export default function Review() {
  const [nonce, setNonce] = useState(0);
  const photos = useAsync(() => api.photos({ limit: 100 }), [nonce]);

  const reading = (photos.data ?? []).filter(
    (photo) => photo.status === "pending" || photo.status === "processing",
  ).length;

  useEffect(() => {
    const refresh = () => {
      // A backgrounded tab is a phone in a pocket: stop asking until it comes back.
      if (!document.hidden) setNonce((value) => value + 1);
    };
    const timer = setInterval(refresh, reading > 0 ? POLL_BUSY_MS : POLL_IDLE_MS);
    // And catch up the moment it does, rather than after another full interval.
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [reading]);

  const pending = (photos.data ?? [])
    .filter((photo) => photo.status !== "reviewed")
    // Oldest first, unlike everywhere else in the app: the photographer works through
    // the house in an order, and following it is how the two of you stay in step.
    .reverse();
  const done = (photos.data ?? []).filter((photo) => photo.status === "reviewed");

  return (
    <>
      <Card
        title="Ellenőrzésre vár"
        note={
          reading > 0
            ? `${reading} kép beolvasás alatt…`
            : pending.length > 0
              ? `${pending.length} kép vár rád`
              : "figyelem az új képeket"
        }
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
        <div className="name">
          {photoTitle(photo.item_names, photo.item_count, photo.scene)}
        </div>
        <div className="where">
          {photo.place_path ?? "hely nélkül"} · {dateTime(photo.taken_at ?? photo.created_at)}
          {/* The scene, when there is one worth having, sits under the names rather than
              standing in for them. */}
          {photo.scene && photo.item_names.length > 0 && <> · {photo.scene}</>}
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
