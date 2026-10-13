'use client';
// F26: "Install BimaSaathi" card (Settings). Hidden once the app is already installed.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { promptInstall, useInstallMode } from '@/lib/pwaInstall';

export default function InstallCard() {
  const { t } = useTranslation();
  const mode = useInstallMode();
  const [declined, setDeclined] = useState(false);

  if (mode === 'installed') return null;

  return (
    <section className="card space-y-3" aria-labelledby="install-h">
      <h2 id="install-h">{t('settings.installTitle')}</h2>
      <p className="text-ink-soft">{t('settings.installBody')}</p>

      {mode === 'prompt' && (
        <button
          type="button"
          className="btn-primary w-full"
          onClick={async () => setDeclined(!(await promptInstall()))}
        >
          {t('settings.installBtn')}
        </button>
      )}

      {mode === 'ios' && (
        <ol className="list-decimal space-y-1 pl-6 text-ink-soft">
          <li>{t('settings.installIos1')}</li>
          <li>{t('settings.installIos2')}</li>
          <li>{t('settings.installIos3')}</li>
        </ol>
      )}

      {mode === 'manual' && <p className="text-ink-soft">{t('settings.installManual')}</p>}

      {declined && (
        <p role="status" className="text-ink-muted">
          {t('settings.installLater')}
        </p>
      )}
    </section>
  );
}
