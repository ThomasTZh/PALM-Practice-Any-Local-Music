import { useCallback, useSyncExternalStore } from "react";

import type { PracticeController, PracticeState } from "./practice";

export function usePracticeState(controller: PracticeController): PracticeState {
  const subscribe = useCallback(
    (listener: () => void) => controller.subscribe(listener),
    [controller],
  );
  const getSnapshot = useCallback(() => controller.getState(), [controller]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
