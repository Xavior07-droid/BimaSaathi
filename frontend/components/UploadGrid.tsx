'use client';
// Claim document grid (F18): add photos (gallery or camera), see previews, remove, max 8.
// Presentational: state lives in useClaimDocs, so the parent decides what to do with the files.
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import { formatBytes, CLAIM_DOC_ACCEPT } from '@/lib/validate';
import type { ClaimDoc, DocNotice } from '@/lib/useClaimDocs';

interface Props {
  docs: ClaimDoc[];
  max: number;
  notices: DocNotice[];
  disabled?: boolean;
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
}

export default function UploadGrid({ docs, max, notices, disabled, onAdd, onRemove }: Props) {
  const { t } = useTranslation();
  const galleryRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const full = docs.length >= max;

  const handle = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files ?? []);
    e.target.value = ''; // lets the same photo be chosen again after removing it
    if (list.length) onAdd(list);
  };

  return (
    <section className="space-y-3" aria-labelledby="docs-h">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="docs-h">{t('claim.docsTitle')}</h2>
        <p className="font-semibold text-ink-soft" aria-live="polite" data-testid="doc-count">
          {t('claim.docsCount', { count: docs.length, max })}
        </p>
      </div>

      <input ref={galleryRef} type="file" accept={CLAIM_DOC_ACCEPT} multiple className="hidden" data-testid="doc-input" onChange={handle} />
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden" data-testid="doc-camera-input" onChange={handle} />

      {docs.length > 0 && (
        <ul className="grid grid-cols-2 gap-3" data-testid="doc-grid">
          {docs.map((d) => (
            <li key={d.id} className="relative overflow-hidden rounded-card border border-surface-line bg-surface">
              <div className="aspect-square w-full bg-surface-alt">
                {d.status === 'ready' && d.preview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={d.preview} alt={d.name} className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-ink-soft" role="status">
                    <span aria-hidden="true" className="inline-block h-7 w-7 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
                    <span>{t('claim.compressing')}</span>
                  </div>
                )}
              </div>
              <div className="p-2">
                <p className="truncate font-semibold">{d.name}</p>
                <p className="text-ink-soft">
                  {d.status === 'ready' && d.file ? (
                    <>
                      <span aria-hidden="true">✓ </span>
                      {t('claim.ready')} · {formatBytes(d.file.size)}
                    </>
                  ) : (
                    t('claim.compressing')
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onRemove(d.id)}
                disabled={disabled}
                aria-label={t('claim.removeDoc', { name: d.name })}
                className="absolute right-1 top-1 flex h-12 w-12 items-center justify-center rounded-full bg-surface/95 text-xl font-bold text-danger-fg shadow-card disabled:opacity-50"
              >
                <span aria-hidden="true">✕</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {docs.length === 0 && (
        <div className="card flex flex-col items-center gap-1 border-2 border-dashed py-6 text-center">
          <Icon name="upload" className="h-8 w-8 text-brand-700" />
          <p className="font-semibold">{t('claim.docsEmptyTitle')}</p>
          <p className="text-ink-soft">{t('claim.docsHelp', { max })}</p>
        </div>
      )}

      {!full ? (
        <div className="grid gap-3">
          <button type="button" className="btn-primary w-full" disabled={disabled} onClick={() => galleryRef.current?.click()}>
            <Icon name="upload" />
            {t('claim.addPhotos')}
          </button>
          <button type="button" className="btn-secondary w-full" disabled={disabled} onClick={() => cameraRef.current?.click()}>
            <Icon name="camera" />
            {t('claim.takePhoto')}
          </button>
        </div>
      ) : (
        <p className="chip-info w-full justify-center" role="status">
          <span aria-hidden="true">ℹ</span> {t('claim.full', { max })}
        </p>
      )}

      {notices.length > 0 && (
        <ul role="alert" className="space-y-1 rounded-card border border-warning-line bg-warning-bg p-3 font-medium text-warning-fg">
          {notices.map((n, i) => (
            <li key={`${n.key}-${i}`} className="flex gap-1">
              <span aria-hidden="true">⚠</span> {t(n.key, n.values)}
            </li>
          ))}
        </ul>
      )}

      <p className="text-ink-muted">{t('claim.docsPrivacy')}</p>
    </section>
  );
}
