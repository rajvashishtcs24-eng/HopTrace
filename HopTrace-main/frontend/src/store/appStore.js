import { useSyncExternalStore } from 'react';

/* --- AlertOverlay state --- */
const storeState = {
  alertOpen: false,
  isArmed: false,
  isMuted: false,
  activeIncident: null,
  affectedSubscribers: [],
  seenIncidentIds: new Set(),
  audioCache: new Map(),
};

const listeners = new Set();

function emitChange() {
  listeners.forEach((listener) => listener());
}

export const appStore = {
  getState: () => storeState,

  subscribe: (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  armDemo: () => {
    storeState.isArmed = true;
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      const silentUtterance = new SpeechSynthesisUtterance('');
      window.speechSynthesis.speak(silentUtterance);
    }
    emitChange();
  },

  toggleMute: () => {
    storeState.isMuted = !storeState.isMuted;
    emitChange();
  },

  dismissAlert: () => {
    storeState.alertOpen = false;
    emitChange();
  },

  reopenAlert: () => {
    if (storeState.activeIncident?.id) {
      storeState.alertOpen = true;
      emitChange();
    }
  },

  notifyIncident: (incident, subscribers = [], isInitialLoad = false) => {
    const incId = incident?.id;

    if (!incId) {
      storeState.activeIncident = null;
      storeState.affectedSubscribers = [];
      storeState.alertOpen = false;
      emitChange();
      return;
    }

    storeState.activeIncident = incident;
    storeState.affectedSubscribers = subscribers;

    if (isInitialLoad) {
      storeState.seenIncidentIds.add(incId);
      emitChange();
      return;
    }

    if (!storeState.seenIncidentIds.has(incId)) {
      storeState.seenIncidentIds.add(incId);
      storeState.alertOpen = true;
      emitChange();
    }
  },

  getCachedAudio: (key) => storeState.audioCache.get(key),
  setCachedAudio: (key, url) => storeState.audioCache.set(key, url),
};

export function useAppStore(selector = (s) => s) {
  return useSyncExternalStore(
    appStore.subscribe,
    () => selector(appStore.getState())
  );
}
