export interface TitleParts {
  section: string;
  view?: string;
  scenario?: string;
  suffix: string;
}

const clean = (value: string | undefined): string =>
  value === undefined ? '' : value.trim();

export const buildDocumentTitle = ({
  section,
  view,
  scenario,
  suffix
}: TitleParts): string => {
  const head = clean(section);
  const sub = clean(view);
  const tag = clean(scenario);
  const tail = clean(suffix);

  const lead = sub === '' || sub === head ? head : `${head} · ${sub}`;
  const scoped = tag === '' ? lead : `${lead} · ${tag}`;

  if (scoped === '') {
    return tail;
  }
  return tail === '' ? scoped : `${scoped} — ${tail}`;
};
