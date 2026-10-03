/** Who is using the app right now.
 *
 *  Several people share one household's data, so most screens do not care who you are.
 *  The ones that do - "who paid this", the balance between you - read it from here rather
 *  than each asking the server again.
 */

import { createContext, useContext } from "react";

import type { SessionInfo } from "./api";

export const SessionContext = createContext<SessionInfo | null>(null);

export function useSession(): SessionInfo | null {
  return useContext(SessionContext);
}
