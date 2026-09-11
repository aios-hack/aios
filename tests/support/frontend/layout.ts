import { srcPath } from './paths';

export const THEME_DIR = srcPath('shared', 'theme');
export const APP_STYLES_DIR = srcPath('app', 'styles');
export const CONSOLE_SHELL_DIR = srcPath('app', 'ConsoleScene');
export const COMMAND_PALETTE_DIR = srcPath('features', 'command-palette', 'ui');
export const FIELD_MAP_CARD_DIR = srcPath('jarvis', 'cards', 'FieldMapCard');

export const THEME_FILES = ['tokens.light.css', 'tokens.dark.css', 'fonts.css'];

export const CONSOLE_SHELL_CSS = [
  srcPath('app', 'ConsoleScene', 'ConsoleShell.css'),
  srcPath('widgets', 'console-header', 'ConsoleHeader.css'),
  srcPath('app', 'ConsoleScene', 'ConsoleScene.css')
];

export const PILL_EXEMPT_CSS = [
  srcPath('features', 'timeline-player', 'ui', 'StepControls', 'StepControls.css'),
  srcPath('features', 'timeline-player', 'ui', 'PlaybackSettings', 'PlaybackSettings.css'),
  srcPath('features', 'timeline-player', 'ui', 'TimeScale', 'TimeScale.css'),
  srcPath('features', 'header-controls', 'ui', 'HeaderControls', 'HeaderControls.css'),
  srcPath('features', 'trust-board', 'ui', 'StatusChip', 'StatusChip.css'),
  srcPath('shared', 'ui', 'IconButton', 'IconButton.css')
];

export const TOKENS_CSS = srcPath('shared', 'theme', 'tokens.css');
export const BASE_STYLES_CSS = srcPath('app', 'styles', 'styles.css');
export const PALETTE_CSS = srcPath(
  'features',
  'command-palette',
  'ui',
  'CommandPalette',
  'CommandPalette.css'
);
