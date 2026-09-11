import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WORKSPACES, WORKSPACE_VIEWS } from '../src/shared/router/routes.ts';

const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, '..', 'public', 'jarvis', 'knowledge', 'routes.json');

const payload = {
  version: 1,
  workspaces: WORKSPACES.map((workspace) => ({
    workspace,
    views: [...WORKSPACE_VIEWS[workspace]]
  }))
};

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8');
