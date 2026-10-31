export interface KeyBpmReadoutProps {
  keyLabel: string | null;
  bpm: number | null;
  bpb?: number | null;
}

function formatBpm(bpm: number): string {
  return Number.isInteger(bpm) ? String(bpm) : bpm.toFixed(1);
}

/** Key and tempo readout shared by the analysis and practice views. */
export function KeyBpmReadout({
  keyLabel,
  bpm,
  bpb = null,
}: KeyBpmReadoutProps) {
  return (
    <dl className="key-bpm-readout" aria-label="Key and tempo">
      <div>
        <dt>Key</dt>
        <dd data-testid="key-bpm-key">{keyLabel ?? "—"}</dd>
      </div>
      <div>
        <dt>Tempo</dt>
        <dd data-testid="key-bpm-value">
          {bpm === null ? "—" : `${formatBpm(bpm)} BPM`}
        </dd>
      </div>
      {bpb !== null && (
        <div>
          <dt>Beats/bar</dt>
          <dd data-testid="key-bpm-meter">{bpb}</dd>
        </div>
      )}
    </dl>
  );
}
