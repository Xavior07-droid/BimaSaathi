'use client';
// F24: "Delete my data" confirmation. Two deliberate steps (tick the box, then press the red button),
// clear about what goes, and the person is signed out afterwards. Native <dialog> = focus trap + Esc.
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@/lib/auth';
import { errorMessageKey } from '@/lib/errors';
import { clearLocalAppData } from '@/lib/localData';
import { useDeleteMyData } from '@/lib/queries';

interface Props {
  open: boolean;
  onClose: () => void;
}

const ITEMS = ['policies', 'reminders', 'claims', 'token'] as const;

export default function DeleteDataDialog({ open, onClose }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const { signOut } = useAuth();
  const del = useDeleteMyData();
  const [sure, setSure] = useState(false);
  const done = del.isSuccess;

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setSure(false);
      del.reset();
      d.showModal();
    }
    if (!open && d.open) d.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const finish = () => {
    // Local copies are wiped only after the server confirmed the deletion.
    clearLocalAppData(qc);
    void signOut();
  };

  const run = () => {
    del.mutate(undefined, { onSuccess: () => clearLocalAppData(qc) });
  };

  const requestClose = () => {
    if (del.isPending) return;
    if (done) finish();
    onClose();
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby="del-h"
      onCancel={(e) => {
        e.preventDefault(); // Esc: route through requestClose so we never close mid-delete
        requestClose();
      }}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) requestClose();
      }}
      className="fixed inset-0 m-auto h-fit max-h-[90vh] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-card border-0 bg-surface p-0 text-ink shadow-card backdrop:bg-black/50"
    >
      <div className="space-y-4 p-4">
        {done ? (
          <>
            <h2 id="del-h">{t('settings.deleteDone')}</h2>
            <p role="status" className="chip-success">
              <span aria-hidden="true">✓</span> {t('settings.deleteDoneBody')}
            </p>
            <button type="button" className="btn-primary w-full" onClick={requestClose}>
              {t('auth.signOut')}
            </button>
          </>
        ) : (
          <>
            <h2 id="del-h">{t('settings.confirmTitle')}</h2>
            <p className="text-ink-soft">{t('settings.confirmBody')}</p>
            <ul className="list-disc space-y-1 pl-6">
              {ITEMS.map((k) => (
                <li key={k}>{t(`settings.items.${k}`)}</li>
              ))}
            </ul>
            <p className="font-semibold text-danger-fg">{t('settings.irreversible')}</p>

            <label className="flex min-h-touch cursor-pointer items-start gap-3 rounded-card border border-surface-line p-3">
              <input
                type="checkbox"
                checked={sure}
                onChange={(e) => setSure(e.target.checked)}
                disabled={del.isPending}
                className="mt-1 h-5 w-5 shrink-0 accent-danger-solid"
              />
              <span>{t('settings.confirmCheck')}</span>
            </label>

            {del.isError && (
              <p role="alert" className="flex gap-1 text-danger-fg">
                <span aria-hidden="true">✕</span> {t(errorMessageKey(del.error))}
              </p>
            )}

            <div className="grid gap-2">
              <button
                type="button"
                onClick={run}
                disabled={!sure || del.isPending}
                className="btn-lg min-h-touch w-full rounded-card bg-danger-solid px-4 font-semibold text-white disabled:opacity-50"
              >
                {del.isPending ? t('settings.deleting') : t('settings.confirmGo')}
              </button>
              <button type="button" className="btn-secondary w-full" onClick={requestClose} disabled={del.isPending}>
                {t('common.cancel')}
              </button>
            </div>
          </>
        )}
      </div>
    </dialog>
  );
}
