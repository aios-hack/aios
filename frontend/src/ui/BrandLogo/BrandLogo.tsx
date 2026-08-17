import { useT } from '../../i18n/I18nContext';
import './BrandLogo.css';

export const BrandLogo = () => {
  const t = useT();

  return (
    <picture className="brand-logo">
      <img
        className="brand-logo-image brand-logo-image--light"
        src="/brand/bsr-light.png"
        alt={t('app.brandAlt')}
        width={2000}
        height={830}
      />
      <img
        className="brand-logo-image brand-logo-image--dark"
        src="/brand/bsr-dark.png"
        alt=""
        aria-hidden="true"
        width={2000}
        height={830}
      />
    </picture>
  );
};
