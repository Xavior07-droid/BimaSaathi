'use client';
// Home / Upload (F8): pick a PDF or photo, take a picture, or try the sample policy.
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import Icon from '@/components/Icon';
import LanguageSwitcher from '@/components/LanguageSwitcher';
import PrivacyWarning from '@/components/PrivacyWarning';
import { rememberPolicyId } from '@/lib/currentPolicy';
import { errorMessageKey } from '@/lib/errors';
import { useIngest, useIngestSample } from '@/lib/queries';
import { ACCEPT_ATTR, formatBytes, isImageFile, validateUploadFile } from '@/lib/validate';
import type { IngestResponse } from '@/lib/types';

const STEPS = ['how1', 'how2', 'how3'] as const;

export default function Home() {
  const { t } = useTranslation();
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const ingest = useIngest();
  const ingestSample = useIngestSample();
  const busy = ingest.isPending || ingestSample.isPending;

  // Thumbnail for photos; always release the object URL.
  useEffect(() => {
    if (!file || !isImageFile(file)) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const choose = (f: File | undefined) => {
    ingest.reset();
    ingestSample.reset();
    if (!f) return;
    const problem = validateUploadFile(f);
    setErrorKey(problem);
    setFile(problem ? null : f);
  };

  const onDone = (res: IngestResponse) => {
    rememberPolicyId(res.policy_id);
    router.push(`/processing?id=${encodeURIComponent(res.policy_id)}`);
  };
  const onFail = (e: unknown) => setErrorKey(errorMessageKey(e));

  const upload = () => {
    if (!file) return;
    setErrorKey(null);
    ingest.mutate(file, { onSuccess: onDone, onError: onFail });
  };
  const trySample = () => {
    setErrorKey(null);
    ingestSample.mutate(undefined, { onSuccess: onDone, onError: onFail });
  };
  const clear = () => {
    setFile(null);
    setErrorKey(null);
    ingest.reset();
  };

  const pick = (ref: React.RefObject<HTMLInputElement>) => {
    setErrorKey(null);
    ref.current?.click();
  };

  return (
    <div className="space-y-5">
      <section>
        <h1>{t('home.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('home.subtitle')}</p>
        <LanguageSwitcher className="mt-3" />
      </section>

      {/* Hidden native inputs, opened by the big buttons below. value reset lets the same file be re-chosen. */}
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          choose(e.target.files?.[0]);
          e.target.value = '';
        }}
      />
      <input
        ref={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        data-testid="camera-input"
        onChange={(e) => {
          choose(e.target.files?.[0]);
          e.target.value = '';
        }}
      />

      {!file ? (
        <section
          className={`card space-y-3 border-2 border-dashed ${dragging ? 'border-brand-600 bg-brand-50' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            choose(e.dataTransfer.files?.[0]);
          }}
        >
          <button type="button" onClick={() => pick(fileInput)} disabled={busy} className="btn-primary btn-lg w-full">
            <Icon name="upload" />
            {t('home.upload')}
          </button>
          <button type="button" onClick={() => pick(cameraInput)} disabled={busy} className="btn-secondary w-full">
            <Icon name="camera" />
            {t('home.camera')}
          </button>
          <p className="text-center text-ink-muted">{t('home.hint')}</p>
        </section>
      ) : (
        <section className="card space-y-3" aria-live="polite">
          <h2>{t('home.selected')}</h2>
          <div className="flex items-center gap-3">
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt="" className="h-16 w-16 shrink-0 rounded-lg border border-surface-line object-cover" />
            ) : (
              <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-brand-100 font-bold text-brand-800">
                PDF
              </span>
            )}
            <div className="min-w-0">
              <p className="truncate font-semibold">{file.name}</p>
              <p className="text-ink-soft">{formatBytes(file.size)}</p>
            </div>
          </div>
          <button type="button" onClick={upload} disabled={busy} className="btn-primary btn-lg w-full">
            {ingest.isPending ? (
              <>
                <span aria-hidden="true" className="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
                {t('home.uploading')}
              </>
            ) : (
              t('home.read')
            )}
          </button>
          <button type="button" onClick={clear} disabled={busy} className="btn-ghost w-full">
            {t('home.remove')}
          </button>
        </section>
      )}

      {errorKey && (
        <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 font-medium text-danger-fg">
          ✕ {t(errorKey)}
        </p>
      )}

      <PrivacyWarning compact />

      <section className="card space-y-2">
        <button type="button" onClick={trySample} disabled={busy} className="btn-secondary w-full">
          {ingestSample.isPending ? t('home.uploading') : t('home.sample')}
        </button>
        <p className="text-center text-ink-muted">{t('home.sampleNote')}</p>
      </section>

      <section>
        <h2>{t('home.howTitle')}</h2>
        <ol className="mt-3 space-y-3">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-100 font-bold text-brand-800">
                {i + 1}
              </span>
              <span>{t(`home.${s}`)}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
