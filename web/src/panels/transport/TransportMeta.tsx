export interface TransportMetaProps {
  projectTitle: string | null;
  keyLabel: string | null;
  bpm: number | null;
  bpb: number | null;
}

/** Track name, key and tempo shown at the right of the stage toolbar. */
export function TransportMeta({
  projectTitle,
  keyLabel,
  bpm,
  bpb,
}: TransportMetaProps) {
  const bpmText =
    bpm === null ? "—" : `${Math.round(bpm * 10) / 10} · ${bpb ?? 4}/4`;
  return (
    <dl className="transport-meta" aria-label="Track details">
      <div>
        <dt>Track</dt>
        <dd data-testid="project-title">{projectTitle ?? "No project"}</dd>
      </div>
      <div>
        <dt>Key</dt>
        <dd data-testid="key-readout">{keyLabel ?? "—"}</dd>
      </div>
      <div>
        <dt>BPM</dt>
        <dd data-testid="bpm-readout">{bpmText}</dd>
      </div>
    </dl>
  );
}
