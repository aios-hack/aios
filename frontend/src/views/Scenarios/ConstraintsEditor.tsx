import { useRef, useState } from 'react';
import { useT } from '../../i18n/I18nContext';
import { InfoHint } from '../../ui/InfoHint';
import { YEAR_SECTIONS } from './constraints';
import { InfrastructureTable } from './InfrastructureTable';
import { OutageTable } from './OutageTable';
import { parseJsonText, type ParseFailure } from './parseDocument';
import { useEditor } from './useEditor';
import { YearSectionTable } from './YearSectionTable';
import './ScenariosEditor.css';

interface ConstraintsEditorProps {
  nIntervals: number;
}

const DOWNLOAD_NAME = 'constraints.json';

export const ConstraintsEditor = ({ nIntervals }: ConstraintsEditorProps) => {
  const t = useT();
  const editor = useEditor(nIntervals);
  const fileInput = useRef<HTMLInputElement>(null);
  const [loadError, setLoadError] = useState<ParseFailure | null>(null);
  const [loadedName, setLoadedName] = useState<string | null>(null);

  const blocked = editor.errors.length > 0;

  const handleDownload = () => {
    const text = JSON.stringify(editor.document, null, 2);
    const blob = new Blob([text], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = DOWNLOAD_NAME;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleUpload = async (file: File) => {
    const result = parseJsonText(await file.text(), nIntervals);
    if (!result.ok) {
      setLoadError(result.error);
      setLoadedName(null);
      return;
    }
    editor.setState(result.state);
    setLoadError(null);
    setLoadedName(file.name);
  };

  return (
    <section className="scenarios-editor">
      <header className="scenarios-editor-head">
        <div className="scenarios-editor-intro">
          <span className="scenarios-editor-title-row">
            <h3 className="scenarios-heading">{t('scenarios.editor.title')}</h3>
            <InfoHint
              label={t('scenarios.editor.hintLabel')}
              text={t('scenarios.editor.downloadHint')}
            />
          </span>
          <p className="scenarios-note">{t('scenarios.editor.note')}</p>
          <p className="scenarios-note">{t('scenarios.editor.emptyNote')}</p>
        </div>
        <div className="scenarios-editor-actions">
          <button
            type="button"
            className="scenarios-button scenarios-button-primary"
            disabled={blocked}
            onClick={handleDownload}
          >
            {t('scenarios.action.download')}
          </button>
          <button
            type="button"
            className="scenarios-button"
            onClick={() => fileInput.current?.click()}
          >
            {t('scenarios.action.upload')}
          </button>
          <input
            ref={fileInput}
            className="scenarios-visually-hidden"
            type="file"
            accept="application/json,.json"
            aria-label={t('scenarios.action.upload')}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) {
                void handleUpload(file);
              }
            }}
          />
        </div>
      </header>

      {blocked && (
        <p className="scenarios-banner scenarios-banner-error" role="alert">
          {t('scenarios.error.blocked', { count: editor.errors.length })}
        </p>
      )}
      {loadError && (
        <p className="scenarios-banner scenarios-banner-error" role="alert">
          {t(`scenarios.${loadError.messageKey}`, loadError.params)}
        </p>
      )}
      {loadedName && !loadError && (
        <p className="scenarios-banner scenarios-banner-ok">
          {t('scenarios.load.ok', { name: loadedName })}
        </p>
      )}

      {YEAR_SECTIONS.map((section) => (
        <YearSectionTable
          key={section}
          section={section}
          rows={editor.state.sections[section]}
          errors={editor.errors}
          onChange={(key, field, value) => editor.changeYear(section, key, field, value)}
          onAdd={() => editor.addYear(section)}
          onRemove={(key) => editor.removeYear(section, key)}
        />
      ))}

      <OutageTable
        rows={editor.state.outages}
        errors={editor.errors}
        nIntervals={nIntervals}
        onChange={editor.changeOutage}
        onAdd={editor.addOutage}
        onRemove={editor.removeOutage}
      />

      <InfrastructureTable
        rows={editor.state.infrastructure}
        errors={editor.errors}
        onChange={editor.changePair}
        onAdd={editor.addPair}
        onRemove={editor.removePair}
      />

      <details className="scenarios-preview">
        <summary className="scenarios-preview-summary">{t('scenarios.preview.title')}</summary>
        <pre className="scenarios-preview-body" data-testid="constraints-preview">
          {JSON.stringify(editor.document, null, 2)}
        </pre>
      </details>
    </section>
  );
};
