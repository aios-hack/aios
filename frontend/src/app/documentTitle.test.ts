import { describe, expect, it } from 'vitest';
import { buildDocumentTitle } from './documentTitle';

describe('document title', () => {
  it('names the section and the view so sibling tabs stay distinct', () => {
    expect(
      buildDocumentTitle({ section: 'История', view: 'Матрица', suffix: 'AIOS' })
    ).toBe('История · Матрица — AIOS');
  });

  it('drops the view when it repeats the section', () => {
    expect(
      buildDocumentTitle({ section: 'Обзор', view: 'Обзор', suffix: 'AIOS' })
    ).toBe('Обзор — AIOS');
  });

  it('omits the view when there is none', () => {
    expect(buildDocumentTitle({ section: 'Деньги', suffix: 'AIOS' })).toBe(
      'Деньги — AIOS'
    );
  });

  it('names the scenario so two scenarios are not confused', () => {
    expect(
      buildDocumentTitle({
        section: 'Решения',
        view: 'Правила',
        scenario: 'whatif-injection-cut',
        suffix: 'AIOS'
      })
    ).toBe('Решения · Правила · whatif-injection-cut — AIOS');
  });

  it('leaves the base scenario unnamed', () => {
    expect(
      buildDocumentTitle({ section: 'Поле', view: 'Проекция', suffix: 'AIOS' })
    ).toBe('Поле · Проекция — AIOS');
  });

  it('treats blank and whitespace parts as absent', () => {
    expect(
      buildDocumentTitle({
        section: 'Поле',
        view: '   ',
        scenario: '',
        suffix: 'AIOS'
      })
    ).toBe('Поле — AIOS');
  });

  it('survives an empty suffix without a trailing dash', () => {
    expect(
      buildDocumentTitle({ section: 'Обзор', view: 'Фонд', suffix: '' })
    ).toBe('Обзор · Фонд');
  });

  it('returns the suffix alone when nothing else is known', () => {
    expect(buildDocumentTitle({ section: '', suffix: 'AIOS' })).toBe('AIOS');
  });
});
