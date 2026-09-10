export const CONSOLE_OVERLAY_ID = 'console-overlay';

export const consoleOverlayHost = (): HTMLElement => {
  if (typeof document === 'undefined') {
    throw new Error('console overlay host requires a document');
  }
  return document.getElementById(CONSOLE_OVERLAY_ID) ?? document.body;
};
