import { readFileSync } from 'node:fs';
import { srcPath } from './paths';

export const THEME_DIR = srcPath('shared', 'theme');
export const APP_STYLES_DIR = srcPath('app', 'styles');
export const CONSOLE_SHELL_DIR = srcPath('app', 'App');
export const COMMAND_PALETTE_DIR = srcPath('features', 'command-palette', 'ui');
export const FIELD_MAP_CARD_DIR = srcPath('jarvis', 'cards', 'FieldMapCard');

export const THEME_FILES = ['tokens.light.css', 'tokens.dark.css', 'fonts.css'];

export const CONSOLE_SHELL_CSS = [
  srcPath('app', 'App', 'ConsoleShell.css'),
  srcPath('app', 'App', 'ConsoleHeader.css'),
  srcPath('app', 'ConsoleScene', 'ConsoleScene.css')
];

export const PILL_EXEMPT_CSS = [
  srcPath('features', 'timeline-player', 'ui', 'StepControls', 'StepControls.css'),
  srcPath('features', 'timeline-player', 'ui', 'PlaybackSettings', 'PlaybackSettings.css'),
  srcPath('features', 'timeline-player', 'ui', 'TimeScale', 'TimeScale.css'),
  srcPath('features', 'timeline-player', 'ui', 'TimeScale', 'TimeScalePlayer.css'),
  srcPath('features', 'header-controls', 'ui', 'HeaderControls', 'HeaderControls.css'),
  srcPath('features', 'trust-board', 'ui', 'StatusChip', 'StatusChip.css'),
  srcPath('shared', 'ui', 'IconButton', 'IconButton.css')
];

export const APP_SHELL_CSS = srcPath('app', 'App', 'ConsoleShell.css');
export const TOKENS_CSS = srcPath('shared', 'theme', 'tokens.css');
export const BASE_STYLES_CSS = srcPath('app', 'styles', 'styles.css');
export const PALETTE_CSS = srcPath(
  'features',
  'command-palette',
  'ui',
  'CommandPalette',
  'CommandPalette.css'
);

export const pageUiPath = (page: string, component: string, file: string): string =>
  srcPath('pages', page, 'ui', component, file);

export const COUNCIL_CSS = {
  council: pageUiPath('council', 'Council', 'Council.css'),
  field: pageUiPath('council', 'Council', 'CouncilField.css'),
  groups: pageUiPath('council', 'Council', 'CouncilGroups.css'),
  wells: pageUiPath('council', 'Council', 'CouncilWells.css')
};

export const CHRONOMAP_CSS = pageUiPath('history-matrix', 'Chronomap', 'Chronomap.css');
export const CHRONO_TOOLTIP_CSS = pageUiPath(
  'history-matrix',
  'ChronoTooltip',
  'ChronoTooltip.css'
);
export const FIELD_PROJECTION_CSS = pageUiPath(
  'field-projection',
  'FieldProjection',
  'FieldProjection.css'
);
export const WELLS_TABLE_CSS = pageUiPath('history-table', 'WellsTable', 'WellsTable.css');
export const WALL_OF_LIVES_CSS = pageUiPath('history-wall', 'WallOfLives', 'WallOfLives.css');
export const ABLATION_TABLE_CSS = pageUiPath('money-rank', 'AblationTable', 'AblationTable.css');
export const ABLATION_CELLS_CSS = pageUiPath('money-rank', 'AblationTable', 'AblationCells.css');
export const SELECTION_RINGS_CSS = srcPath(
  'entities',
  'wells',
  'ui',
  'SelectionRings',
  'SelectionRings.css'
);

export const cssBlock = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return css.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`))?.[0] ?? '';
};

export const pxOf = (css: string, value: string): number => {
  const direct = value.trim().match(/^(-?[\d.]+)px$/);
  if (direct !== null) {
    return Number(direct[1]);
  }
  const token = value.trim().match(/^var\((--[\w-]+)\)$/);
  if (token === null) {
    return Number.NaN;
  }
  const declared = css.match(new RegExp(`${token[1] as string}:\\s*([^;]+);`));
  return declared === null ? Number.NaN : pxOf(css, declared[1] as string);
};

export const declaredPx = (css: string, selector: string, property: string): number => {
  const block = cssBlock(css, selector);
  const declared = block.match(new RegExp(`(?<![\\w-])${property}:\\s*([^;]+);`));
  return declared === null ? Number.NaN : pxOf(css, declared[1] as string);
};

export const SCREEN_READER_ONLY = '.visually-hidden';

export const hidesVisuallyOnly = (selector: string): boolean => {
  const css = readFileSync(BASE_STYLES_CSS, 'utf-8');
  const rule = css.match(
    new RegExp(`([^}]*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[^{]*)\\{([^}]*)\\}`)
  );
  if (rule === null) {
    return false;
  }
  const body = rule[2] as string;
  return (
    body.includes('clip-path') &&
    !body.includes('display: none') &&
    !body.includes('visibility: hidden')
  );
};
