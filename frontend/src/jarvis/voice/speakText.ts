export const SPEAK_URL = '/api/jarvis/speak';
export const VOICES_URL = '/api/jarvis/voices';

export const speakLang = (lang: string): string => (lang === 'en' ? 'en-US' : 'ru-RU');

export const plainSpeech = (source: string): string => {
  const lines: string[] = [];
  let fenced = false;
  for (const raw of source.split('\n')) {
    if (raw.trimStart().startsWith('```')) {
      fenced = !fenced;
      continue;
    }
    if (fenced) {
      continue;
    }
    lines.push(
      raw
        .replace(/^#{1,6}\s*/, '')
        .replace(/^\s*[-*+]\s+/, '')
        .replace(/^\s*>\s?/, '')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    );
  }
  return lines.join(' ').replace(/\s+/g, ' ').trim();
};

export const pickVoice = (
  voices: readonly SpeechSynthesisVoice[],
  lang: string
): SpeechSynthesisVoice | null => {
  const wanted = speakLang(lang).toLowerCase();
  const code = wanted.slice(0, 2);
  const matching = voices.filter((voice) => voice.lang.toLowerCase().startsWith(code));
  const pool = matching.length > 0 ? matching : voices;
  const natural = pool.find((voice) => /natural|online/i.test(voice.name));
  if (natural !== undefined) {
    return natural;
  }
  const exact = pool.find((voice) => voice.lang.toLowerCase() === wanted);
  return exact ?? pool[0] ?? null;
};

export const speechSynthesisSupported = (): boolean =>
  typeof window !== 'undefined' && typeof window.speechSynthesis !== 'undefined';

export const fetchSpeech = async (
  text: string,
  lang: string,
  fetchImpl?: typeof fetch
): Promise<ArrayBuffer | null> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(SPEAK_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, lang })
    });
    if (!response.ok) {
      return null;
    }
    return await response.arrayBuffer();
  } catch {
    return null;
  }
};
