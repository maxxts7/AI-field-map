import { useEffect } from "react";

export function ComingSoon({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet sheet--compact" onClick={(e) => e.stopPropagation()}>
        <button className="sheet__close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <div className="soon__badge">Coming soon</div>
        <h2 className="soon__title">Create your own map</h2>
        <p className="soon__text">
          Soon you'll be able to describe the axis you care about, and we'll re-sort the
          whole corpus into a custom lens shaped by your question — the same way Methodology,
          Approach, Threat, Contribution, and Future work today.
        </p>
      </div>
    </div>
  );
}
