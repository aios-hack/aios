import { createContext, useContext } from 'react';
import type {
  JarvisSessionValue,
  JarvisSphereValue,
  JarvisVoiceValue
} from '@/jarvis/model/jarvisValue';

export const JarvisSessionContext = createContext<JarvisSessionValue | null>(null);
export const JarvisVoiceContext = createContext<JarvisVoiceValue | null>(null);
export const JarvisSphereContext = createContext<JarvisSphereValue | null>(null);

export const useJarvisSessionContext = (): JarvisSessionValue => {
  const value = useContext(JarvisSessionContext);
  if (value === null) {
    throw new Error('useJarvisSessionContext must be used within JarvisProvider');
  }
  return value;
};

export const useOptionalJarvisSession = (): JarvisSessionValue | null =>
  useContext(JarvisSessionContext);

export const useJarvisVoice = (): JarvisVoiceValue => {
  const value = useContext(JarvisVoiceContext);
  if (value === null) {
    throw new Error('useJarvisVoice must be used within JarvisProvider');
  }
  return value;
};

export const useJarvisSphere = (): JarvisSphereValue => {
  const value = useContext(JarvisSphereContext);
  if (value === null) {
    throw new Error('useJarvisSphere must be used within JarvisProvider');
  }
  return value;
};

export const useOptionalJarvisSphere = (): JarvisSphereValue | null =>
  useContext(JarvisSphereContext);

export const useOptionalJarvisVoice = (): JarvisVoiceValue | null =>
  useContext(JarvisVoiceContext);
