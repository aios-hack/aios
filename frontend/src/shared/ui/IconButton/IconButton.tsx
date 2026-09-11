import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import './IconButton.css';

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  glyph?: boolean;
  children: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ label, glyph = false, className, children, title, ...rest }, ref) => (
    <button
      {...rest}
      ref={ref}
      type="button"
      className={className === undefined ? 'icon-button' : `icon-button ${className}`}
      aria-label={label}
      title={title ?? label}
    >
      {glyph ? (
        <span className="icon-button-glyph" aria-hidden="true">
          {children}
        </span>
      ) : (
        children
      )}
    </button>
  )
);

IconButton.displayName = 'IconButton';
