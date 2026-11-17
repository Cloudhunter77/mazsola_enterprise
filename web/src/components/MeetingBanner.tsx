/** "Még nem volt havi megbeszélés" - from the 1st of a month until the meeting that plans it.
 *
 *  Shown on Rögzítés, where the app is opened most, and under Pénz. It asks again on every
 *  navigation, so it disappears the moment the meeting is closed rather than at the next
 *  reload. The question is one small query; a banner that lingers after the meeting would
 *  teach you to ignore it.
 */

import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { monthLabel } from "../lib/budget";
import { useAsync } from "./ui";

export default function MeetingBanner({ pathname }: { pathname: string }) {
  const status = useAsync(() => api.budgetStatus(), [pathname]);
  const data = status.data;
  if (!data?.meeting_due) return null;

  const first = data.current === null;
  return (
    <Link className="banner" to="/megbeszeles">
      <span>
        <strong>{first ? "Még nincs költségvetés" : "Még nem volt havi megbeszélés"}</strong>
        <span className="banner-note">
          {first
            ? " · az első megbeszéléssel indul"
            : ` · ${monthLabel(data.suggested_month)} még nincs megtervezve`}
        </span>
      </span>
      <span className="banner-action">Megbeszélés →</span>
    </Link>
  );
}
