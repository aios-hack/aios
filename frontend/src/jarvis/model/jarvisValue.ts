import type { ConsoleAction } from '@/jarvis/actions/lib/consoleAction';
import type { Transcript } from '@/jarvis/model/prefs';
import type { SphereState } from '@/jarvis/sphere/lib/sphereState';
import type { TransportMode } from '@/jarvis/transport/JarvisTransport';
import type { JarvisAskContext } from '@/jarvis/transport/events';
import type { JarvisCapabilities } from '@/jarvis/transport/sseTransport';
import type { TransitionPhase, TransitionState } from '@/jarvis/model/transition';
import type { JarvisSession } from '@/jarvis/provider/useJarvisSession';

export interface JarvisSessionValue extends JarvisSession {
  transition: TransitionState;
  visible: boolean;
  moving: boolean;
  open: () => void;
  close: () => void;
  settle: (phase: TransitionPhase) => void;
  crossfade: boolean;
  requestCrossfade: () => void;
  askContext: JarvisAskContext;
  transportMode: TransportMode;
  capabilities: JarvisCapabilities;
  retry: () => void;
  applyAction: (action: ConsoleAction) => void;
}

export interface JarvisVoiceValue {
  micOpen: boolean;
  setMicOpen: (open: boolean) => void;
  transcript: Transcript;
  setTranscript: (value: Transcript) => void;
  sttError: string | null;
  setSttError: (code: string | null) => void;
  confirmVoice: boolean;
  toggleConfirmVoice: () => void;
  voiceAsked: boolean;
  noteVoiceAsked: () => void;
  clearVoiceAsked: () => void;
  speakEnabled: boolean;
  toggleSpeak: () => void;
}

export interface JarvisSphereValue {
  sphereState: SphereState;
  setHovering: (hovering: boolean) => void;
  audioLevel: number;
  setAudioLevel: (level: number) => void;
}
