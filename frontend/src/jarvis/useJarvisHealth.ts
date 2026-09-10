import { useCallback, useEffect, useRef, useState } from 'react';
import {
  OFFLINE,
  fetchCapabilities,
  type JarvisCapabilities
} from './transport/sseTransport';

export const HEALTH_POLL_MS = 5000;

export interface JarvisHealth {
  capabilities: JarvisCapabilities;
  probe: () => void;
}

export const useJarvisHealth = (active: boolean, failing: boolean): JarvisHealth => {
  const [capabilities, setCapabilities] = useState<JarvisCapabilities>(OFFLINE);
  const alive = useRef(true);

  const probe = useCallback(() => {
    void fetchCapabilities().then((next) => {
      if (alive.current) {
        setCapabilities(next);
      }
    });
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!active) {
      return;
    }
    probe();
  }, [active, probe]);

  useEffect(() => {
    if (!active || !failing) {
      return;
    }
    const id = window.setInterval(probe, HEALTH_POLL_MS);
    return () => window.clearInterval(id);
  }, [active, failing, probe]);

  return { capabilities, probe };
};
