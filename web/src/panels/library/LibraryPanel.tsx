import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import type { StudioApi } from "../../api/client";
import { formatClock } from "../../state/format";
import type { LibraryEntry } from "../../state/types";

export interface LibraryPanelProps {
  api: StudioApi;
  onOpen: (projectId: string) => void;
  activeProjectId?: string | null;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Local recording library: list, import, open. */
export function LibraryPanel({
  api,
  onOpen,
  activeProjectId = null,
}: LibraryPanelProps) {
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    try {
      setEntries(await api.listLibrary());
      setError(null);
    } catch (failure) {
      setError(errorMessage(failure));
      setEntries(null);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const entry = await api.importRecording(file);
      await load();
      onOpen(entry.projectId ?? entry.id);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setImporting(false);
    }
  }

  return (
    <aside className="library" aria-label="Library">
      <div className="library-header">
        <h2>Library</h2>
        <label className="library-import">
          <span>{importing ? "Importing…" : "Import"}</span>
          <input
            type="file"
            accept="audio/*,video/*"
            aria-label="Import recording"
            disabled={importing}
            onChange={handleImport}
          />
        </label>
      </div>

      {error !== null && (
        <p className="library-error" role="alert">
          {error}
        </p>
      )}
      {entries === null && error === null && (
        <p className="library-note">Loading library…</p>
      )}
      {entries !== null && entries.length === 0 && (
        <p className="library-note">No recordings yet.</p>
      )}
      {entries !== null && entries.length > 0 && (
        <ul className="library-list">
          {entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className="library-entry"
                aria-label={`Open ${entry.title}`}
                aria-current={
                  activeProjectId === (entry.projectId ?? entry.id)
                    ? "true"
                    : undefined
                }
                onClick={() => onOpen(entry.projectId ?? entry.id)}
              >
                <span className="library-title">{entry.title}</span>
                <span className="library-duration">
                  {formatClock(entry.durationSeconds)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
