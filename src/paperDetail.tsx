import { createContext, useContext } from "react";

/** App-wide hook to open the per-paper lineage / future detail overlay.
 * Null when no handler is mounted, so paper lists can render normally. */
export const OpenPaperContext = createContext<((docId: string) => void) | null>(null);

export const useOpenPaper = () => useContext(OpenPaperContext);
