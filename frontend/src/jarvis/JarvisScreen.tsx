import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n/I18nContext';
import type { ConsoleAction } from './actions/consoleAction';
import { useJarvis } from './JarvisContext';
import { Caption } from './scene/Caption';
import { ContextRibbon } from './scene/ContextRibbon';
import { InputDock } from './scene/InputDock';
import { Orbit } from './scene/Orbit';
import { SceneStack } from './scene/SceneStack';
import { SceneStatus } from './scene/SceneStatus';
import { Suggestions } from './scene/Suggestions';
import { STAGE_SLOT_ID } from './scene/stageSlot';
import { activeScene } from './scenes';
import { useFocusTrap } from './useFocusTrap';
import { useSpeak } from './voice/useSpeak';
import './JarvisScreen.css';

const WHEEL_STEP_PX = 24;

export const JarvisScreen = () => {
  const { lang, t } = useI18n();
  const {
    scenes,
    askQuestion,
    selectScene,
    close,
    transition,
    speakEnabled,
    setAudioLevel,
    micOpen,
    applyAction
  } = useJarvis();
  const ref = useRef<HTMLDivElement>(null);
  const [focusSignal, setFocusSignal] = useState(0);
  const open = transition.phase === 'open';
  const scene = activeScene(scenes);

  useFocusTrap(ref, open, close);
  useSpeak({
    enabled: speakEnabled,
    lang,
    text: scene?.caption ?? null,
    onEnvelope: setAudioLevel
  });

  useEffect(() => {
    if (open) {
      setFocusSignal((value) => value + 1);
    }
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === '/' && !(event.target instanceof HTMLTextAreaElement)) {
        event.preventDefault();
        setFocusSignal((value) => value + 1);
        return;
      }
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (event.target instanceof HTMLTextAreaElement) {
          return;
        }
        event.preventDefault();
        selectScene(scenes.activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
      }
    };
    const onWheel = (event: WheelEvent) => {
      if (event.target instanceof Element && event.target.closest('.jarvis-card-body')) {
        return;
      }
      if (Math.abs(event.deltaY) < WHEEL_STEP_PX) {
        return;
      }
      selectScene(scenes.activeIndex + (event.deltaY > 0 ? 1 : -1));
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('wheel', onWheel, { passive: true });
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('wheel', onWheel);
    };
  }, [open, selectScene, scenes.activeIndex]);

  const onOpen = useCallback(
    (action: ConsoleAction) => {
      applyAction(action);
      close();
    },
    [applyAction, close]
  );

  return (
    <div
      className="jarvis-screen"
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label={t('jarvis.dialogLabel')}
    >
      <ContextRibbon />
      <div className="jarvis-screen-body">
        <div className="jarvis-screen-orbit">
          <span className="jarvis-screen-slot" id={STAGE_SLOT_ID} aria-hidden="true" />
          {scene === null ? null : <Orbit cards={scene.cards} onOpen={onOpen} />}
        </div>
        <div className="jarvis-screen-say">
          {scene === null ? (
            <div className="jarvis-screen-empty">
              <p className="jarvis-screen-empty-title">{t('jarvis.emptyTitle')}</p>
              <p className="jarvis-screen-empty-body">{t('jarvis.emptyBody')}</p>
            </div>
          ) : (
            <Caption scene={scene} />
          )}
          <SceneStatus
            status={scenes.status}
            tool={scenes.tool}
            micOpen={micOpen}
            scene={scene}
          />
        </div>
      </div>
      <footer className="jarvis-screen-foot">
        <SceneStack
          scenes={scenes.scenes}
          activeIndex={scenes.activeIndex}
          onSelect={selectScene}
        />
        <Suggestions items={scenes.suggestions} onPick={askQuestion} />
        <InputDock onAsk={askQuestion} focusSignal={focusSignal} />
      </footer>
    </div>
  );
};
