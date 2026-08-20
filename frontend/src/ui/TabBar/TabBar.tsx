import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import './TabBar.css';

interface TabBarProps<Id extends string> {
  ids: readonly Id[];
  active: Id;
  label: string;
  renderLabel: (id: Id) => string;
  onSelect: (id: Id) => void;
}

export const TabBar = <Id extends string>({
  ids,
  active,
  label,
  renderLabel,
  onSelect
}: TabBarProps<Id>) => {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [thumb, setThumb] = useState<CSSProperties>({ opacity: 0 });

  useLayoutEffect(() => {
    const node = refs.current[active];
    if (!node) {
      return;
    }
    const measure = () => {
      setThumb({
        opacity: 1,
        width: `${node.offsetWidth}px`,
        transform: `translateX(${node.offsetLeft}px)`
      });
    };
    measure();
    document.fonts?.ready.then(measure);
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    if (trackRef.current) {
      observer.observe(trackRef.current);
    }
    return () => {
      observer.disconnect();
    };
  }, [active, ids]);

  const moveFocus = (from: Id, delta: number) => {
    const index = ids.indexOf(from);
    const next = ids[(index + delta + ids.length) % ids.length];
    onSelect(next);
    refs.current[next]?.focus();
  };

  return (
    <nav className="tab-bar">
      <div className="tab-bar-track" ref={trackRef} role="tablist" aria-label={label}>
        <span className="tab-bar-thumb" style={thumb} aria-hidden="true" />
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            ref={(node) => {
              refs.current[id] = node;
            }}
            className="tab-bar-tab"
            aria-selected={active === id}
            aria-controls={`panel-${id}`}
            tabIndex={active === id ? 0 : -1}
            onClick={() => onSelect(id)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight') {
                moveFocus(id, 1);
              }
              if (event.key === 'ArrowLeft') {
                moveFocus(id, -1);
              }
            }}
          >
            {renderLabel(id)}
          </button>
        ))}
      </div>
    </nav>
  );
};
