import { useCallback, useMemo, useState } from 'react';
import type { JarvisVoiceValue } from '@/jarvis/model/jarvisValue';
import {
  CONFIRM_KEY,
  EMPTY_TRANSCRIPT,
  SPEAK_KEY,
  readFlag,
  writeFlag,
  type Transcript
} from '@/jarvis/model/prefs';

export const useVoiceState = (): JarvisVoiceValue => {
  const [micOpen, setMicOpen] = useState(false);
  const [transcript, setTranscript] = useState<Transcript>(EMPTY_TRANSCRIPT);
  const [sttError, setSttError] = useState<string | null>(null);
  const [confirmVoice, setConfirmVoice] = useState(() => readFlag(CONFIRM_KEY, false));
  const [voiceAsked, setVoiceAsked] = useState(false);
  const [speakEnabled, setSpeakEnabled] = useState(() => readFlag(SPEAK_KEY, false));

  const toggleSpeak = useCallback(
    () =>
      setSpeakEnabled((value) => {
        writeFlag(SPEAK_KEY, !value);
        return !value;
      }),
    []
  );
  const toggleConfirmVoice = useCallback(
    () =>
      setConfirmVoice((value) => {
        writeFlag(CONFIRM_KEY, !value);
        return !value;
      }),
    []
  );
  const noteVoiceAsked = useCallback(() => setVoiceAsked(true), []);
  const clearVoiceAsked = useCallback(() => setVoiceAsked(false), []);

  return useMemo(
    () => ({
      micOpen,
      setMicOpen,
      transcript,
      setTranscript,
      sttError,
      setSttError,
      confirmVoice,
      toggleConfirmVoice,
      voiceAsked,
      noteVoiceAsked,
      clearVoiceAsked,
      speakEnabled,
      toggleSpeak
    }),
    [
      micOpen,
      transcript,
      sttError,
      confirmVoice,
      toggleConfirmVoice,
      voiceAsked,
      noteVoiceAsked,
      clearVoiceAsked,
      speakEnabled,
      toggleSpeak
    ]
  );
};
