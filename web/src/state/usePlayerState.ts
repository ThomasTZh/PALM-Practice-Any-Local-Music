import { useCallback, useSyncExternalStore } from "react";

import type { PlayerState, StudioPlayer } from "./player";

/**
 * Subscribes a component to the transport seam. The player is responsible for
 * returning a stable state object until something actually changes, which is
 * what makes `useSyncExternalStore` cheap.
 */
export function usePlayerState(player: StudioPlayer): PlayerState {
  const subscribe = useCallback(
    (listener: () => void) => player.subscribe(listener),
    [player],
  );
  const getSnapshot = useCallback(() => player.getState(), [player]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
