import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { LiveRuns } from './LiveRuns';
const document = { injection_limits: { '2007': 30000 }, liquid_limits: {}, production_floors: {}, watercut_limits: {}, well_outages: [], infrastructure: {} };
afterEach(() => vi.unstubAllGlobals());
it('sends current conditions and displays a newly created run', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: 'web-new', status: 'running', message: 'Поиск плана суррогатом…' }) });
  vi.stubGlobal('fetch', fetch);
  render(<LiveRuns document={document} blocked={false} />);
  const button = screen.getByRole('button', { name: 'Найти план суррогатом' }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  await screen.findByText('Поиск плана суррогатом…');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ mode: 'search', constraints: document, budget: 30 });
  expect(button.disabled).toBe(true);
});
it('verifies the saved run without sending changed form conditions', async () => {
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [{ run_id: 'web-saved', status: 'completed', manifest: { predicted_npv: 100, verified_npv: null, sound: null } }] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: 'web-saved', status: 'running', message: 'Полный расчёт OPM…' }) });
  vi.stubGlobal('fetch', fetch);
  render(<LiveRuns document={document} blocked={false} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить план в OPM' }));
  await screen.findByText('Полный расчёт OPM…');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ mode: 'verify', run_id: 'web-saved' });
});
