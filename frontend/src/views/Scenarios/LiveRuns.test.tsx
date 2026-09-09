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

it('shows saved conditions and returns them to the form without starting a run', async () => {
  const onLoadConditions = vi.fn();
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ runs: [{ run_id: 'web-saved', status: 'completed', constraints: document }] }) });
  vi.stubGlobal('fetch', fetch);
  render(<LiveRuns document={{ ...document, injection_limits: {} }} blocked={false} onLoadConditions={onLoadConditions} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Вернуть эти условия в форму' }));
  expect(onLoadConditions).toHaveBeenCalledWith(document);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('shows temporal errors and does not turn an unmeasured error into zero', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ runs: [{
    run_id: 'web-unseen', status: 'completed', unseen_result: {
      focus_year: '2017', fitted_schedule_hashes_count: 833, exact_fit_overlap: false,
      yearly: { '2017': { oil_mass_delta: { absolute_error_pct: null }, liquid_volume_delta: { absolute_error_pct: 5.48 }, injection_volume_delta: { absolute_error_pct: .53 } } },
      paired_comparison: { predicted_npv_change_rub: -240749, opm_npv_change_rub: -11121249 }
    }
  }] }) }));
  render(<LiveRuns document={document} blocked={false} />);
  await screen.findByText('Нефть: не измерено');
  expect(screen.getByText('Жидкость: 5,48%')).toBeTruthy();
  expect(screen.getByText(/Изменение ЧДД к предыдущему проверенному плану/).textContent).toContain('11');
});

const runsReply = (run: Record<string, unknown>) => vi.fn().mockResolvedValue({ ok: true, json: async () => ({ runs: [{ run_id: 'web-p', status: 'completed', ...run }] }) });
const manifest = {
  status: 'verified', predicted_npv: 1, verified_npv: 1, sound: true, schedule_hash: 'a'.repeat(64),
  model_version: 'z-7', npv_head_version: 'head-3', scenario_ood_version: 'ood-2',
  constraints_hash: 'c'.repeat(64), deck_hash: 'd'.repeat(64), git_commit: 'e'.repeat(40),
  opm_image: 'opm:2024.10', seed: '42', search_strategy: 'policy', policy_equilibrium: 'claimed',
  iterations: 30, self_consistent: true
};
it('shows provenance fields when the manifest records them', async () => {
  vi.stubGlobal('fetch', runsReply({ manifest, flow_seconds: 812.5 }));
  render(<LiveRuns document={document} blocked={false} />);
  fireEvent.click(await screen.findByText('Происхождение результата'));
  expect(screen.getByText('агентная политика')).toBeTruthy();
  expect(screen.getByText('z-7')).toBeTruthy();
  expect(screen.getByText('opm:2024.10')).toBeTruthy();
  expect(screen.getByText('812,5 с')).toBeTruthy();
  const hash = screen.getByTitle('c'.repeat(64));
  expect(hash.textContent).toBe(`${'c'.repeat(12)}…`);
});
it('reports a missing provenance field as unrecorded rather than zero or blank', async () => {
  vi.stubGlobal('fetch', runsReply({ manifest: { predicted_npv: 1, verified_npv: null, sound: null, model_version: null } }));
  render(<LiveRuns document={document} blocked={false} />);
  fireEvent.click(await screen.findByText('Происхождение результата'));
  const versions = screen.getByText('Версия модели').parentElement as HTMLElement;
  expect(versions.textContent).toContain('не записано');
  expect(versions.textContent).not.toContain('0');
  expect(screen.getByText('Длительность Flow').parentElement!.textContent).toContain('не записано');
});
it('flags a fallback search and stays silent for the main one', async () => {
  vi.stubGlobal('fetch', runsReply({ manifest: { ...manifest, search_strategy: 'baseline-neighborhood', policy_equilibrium: 'not-claimed', selected_candidate: 'local-change' } }));
  const view = render(<LiveRuns document={document} blocked={false} />);
  expect((await screen.findByRole('note')).textContent).toContain('резервным поиском');
  view.unmount();
  vi.stubGlobal('fetch', runsReply({ manifest }));
  render(<LiveRuns document={document} blocked={false} />);
  await screen.findByText('Происхождение результата');
  expect(screen.queryByRole('note')).toBeNull();
});
it('says the submission bundle is missing instead of showing empty values', async () => {
  vi.stubGlobal('fetch', runsReply({ manifest }));
  render(<LiveRuns document={document} blocked={false} />);
  expect((await screen.findByLabelText('Пакет сдачи')).textContent).toContain('Пакет сдачи не собран');
  expect(screen.queryByText('Заявленный ЧДД')).toBeNull();
});
it('shows the assembled submission bundle with its claimed npv and hashes', async () => {
  vi.stubGlobal('fetch', runsReply({ manifest, submission: {
    canonical_schedule_hash: 'b'.repeat(64), content_hash_submission: 'f'.repeat(64),
    claimed_npv_rub: 1234567, source_run_id: 'web-p', created_at: '2026-09-09T10:00:00Z', schedule_present: true
  } }));
  render(<LiveRuns document={document} blocked={false} />);
  const panel = await screen.findByLabelText('Пакет сдачи');
  expect(panel.textContent).toContain('Пакет собран');
  expect(screen.getByText('Заявленный ЧДД').parentElement!.textContent!.replace(/\s/g, ' ')).toContain('1 234 567 ₽');
  expect(screen.getByText('Состояние проверки').parentElement!.textContent).toContain('проверен полным расчётом');
  expect(screen.getByTitle('b'.repeat(64))).toBeTruthy();
  expect(screen.getByText('Хеш отклика').parentElement!.textContent).toContain('не записано');
});
