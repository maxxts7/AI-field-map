import { useEffect, type ReactNode } from "react";
import evolutionShot from "../assets/help/evolution.png";
import emergingShot from "../assets/help/emerging.png";
import paperDetailShot from "../assets/help/paper-detail.png";

function Step({
  n,
  title,
  children,
  img,
  imgAlt,
}: {
  n: number;
  title: string;
  children: ReactNode;
  img?: string;
  imgAlt?: string;
}) {
  return (
    <div className="help__step">
      <div className="help__num">{n}</div>
      <div className="help__stepbody">
        <h3 className="help__stitle">{title}</h3>
        <p className="help__stext">{children}</p>
        {img && <img className="help__shot" src={img} alt={imgAlt} />}
      </div>
    </div>
  );
}

export function Help({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet sheet--help" onClick={(e) => e.stopPropagation()}>
        <button className="sheet__close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <header className="sheet__head">
          <div className="sheet__kicker">Guide</div>
          <h2 className="sheet__title">How to read this map</h2>
          <p className="sheet__lead">Four things worth knowing before you dig in.</p>
        </header>

        <div className="help__steps">
          <Step n={1} title="Pick a lens">
            The five tabs across the top — Methodology, Approach, Threat, Contribution, Future — are
            different ways of slicing the same corpus. Switching lenses re-sorts every paper into a
            new hierarchy; nothing is added or removed.
          </Step>

          <Step
            n={2}
            title="Watch it evolve, or see what's rising"
            img={evolutionShot}
            imgAlt="The Evolution streamgraph, showing monthly paper volume stacked by sub-topic"
          >
            <b>Evolution</b> renders monthly volume as a streamgraph — a band that swells is gaining
            attention, one that thins is fading. <b>Emerging</b> switches to a ranked list, sorted by
            recent share or growth, for a sharper read on what's hot right now.
          </Step>

          <Step
            n={3}
            title="Drill into a band or row"
            img={emergingShot}
            imgAlt="The Emerging ranked list with a drilled-in paper panel on the right"
          >
            Click any band (Evolution) or row (Emerging) to open its paper list on the right, with
            links out to every paper. Use the breadcrumb above the chart to step back out.
          </Step>

          <Step
            n={4}
            title="Open a paper for its lineage"
            img={paperDetailShot}
            imgAlt="A paper detail sheet showing its description, lineage timeline, and future direction"
          >
            Click any paper to see what it does, the canonical work it traces back to, and where
            that line of research points next — all assigned automatically by Claude.
          </Step>
        </div>
      </div>
    </div>
  );
}
