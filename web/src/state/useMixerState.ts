import { useCallback, useSyncExternalStore } from "react";

import type { MixerController, MixerState } from "./mixer";

export function useMixerState(controller: MixerController): MixerState {
  const subscribe = useCallback(
    (listener: () => void) => controller.subscribe(listener),
    [controller],
  );
  const getSnapshot = useCallback(() => controller.getState(), [controller]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
