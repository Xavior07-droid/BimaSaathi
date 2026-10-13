'use client';
// State for the claim document grid (F18): add (with validation + compression), remove, clear.
// Files live only in memory: they are never written to storage and are sent once to /api/claim/check.
import { useCallback, useEffect, useRef, useState } from 'react';
import { compressImage } from './compressImage';
import { validateClaimDoc } from './validate';

export const MAX_CLAIM_DOCS = 8;

export interface ClaimDoc {
  id: string;
  name: string;
  signature: string; // original name|size|lastModified, used to skip duplicates
  status: 'working' | 'ready';
  file: File | null; // compressed file, set when ready
  preview: string | null; // object URL of the compressed file
}

export interface DocNotice {
  key: string; // i18n key
  values?: Record<string, string | number>;
}

let counter = 0;
const nextId = () => `doc-${Date.now().toString(36)}-${counter++}`;

export function useClaimDocs(max = MAX_CLAIM_DOCS) {
  const [docs, setDocs] = useState<ClaimDoc[]>([]);
  const [notices, setNotices] = useState<DocNotice[]>([]);
  const docsRef = useRef<ClaimDoc[]>([]); // always the latest list (async work reads this)
  const mounted = useRef(true);

  const commit = useCallback((fn: (d: ClaimDoc[]) => ClaimDoc[]) => {
    docsRef.current = fn(docsRef.current);
    if (mounted.current) setDocs(docsRef.current);
  }, []);

  const revoke = (d: ClaimDoc) => {
    if (d.preview) URL.revokeObjectURL(d.preview);
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      docsRef.current.forEach(revoke); // release thumbnails when leaving the screen
    };
  }, []);

  const addFiles = useCallback(
    async (incoming: File[]) => {
      const notes: DocNotice[] = [];
      let tooMany = 0;
      let duplicates = 0;
      const accepted: ClaimDoc[] = [];
      const originals = new Map<string, File>();

      for (const f of incoming) {
        const signature = `${f.name}|${f.size}|${f.lastModified}`;
        if (docsRef.current.some((d) => d.signature === signature) || accepted.some((d) => d.signature === signature)) {
          duplicates++;
          continue;
        }
        const problem = validateClaimDoc(f);
        if (problem) {
          notes.push({ key: problem, values: { name: f.name } });
          continue;
        }
        if (docsRef.current.length + accepted.length >= max) {
          tooMany++;
          continue;
        }
        const doc: ClaimDoc = { id: nextId(), name: f.name, signature, status: 'working', file: null, preview: null };
        accepted.push(doc);
        originals.set(doc.id, f);
      }
      if (tooMany) notes.push({ key: 'claim.tooMany', values: { count: tooMany, max } });
      if (duplicates) notes.push({ key: 'claim.duplicate', values: { count: duplicates } });
      setNotices(notes);
      if (accepted.length === 0) return;

      commit((d) => [...d, ...accepted]);

      // One at a time: decoding several 10 MB photos in parallel can crash low-RAM phones.
      for (const doc of accepted) {
        const original = originals.get(doc.id)!;
        try {
          const small = await compressImage(original);
          const preview = URL.createObjectURL(small);
          if (!docsRef.current.some((d) => d.id === doc.id)) {
            URL.revokeObjectURL(preview); // removed while compressing
            continue;
          }
          commit((d) => d.map((x) => (x.id === doc.id ? { ...x, status: 'ready', file: small, preview } : x)));
        } catch {
          commit((d) => d.filter((x) => x.id !== doc.id));
          if (mounted.current) {
            setNotices((n) => [...n, { key: 'claim.errDocRead', values: { name: original.name } }]);
          }
        }
      }
    },
    [commit, max],
  );

  const remove = useCallback(
    (id: string) => {
      const gone = docsRef.current.find((d) => d.id === id);
      if (gone) revoke(gone);
      commit((d) => d.filter((x) => x.id !== id));
      setNotices([]);
    },
    [commit],
  );

  const clear = useCallback(() => {
    docsRef.current.forEach(revoke);
    commit(() => []);
    setNotices([]);
  }, [commit]);

  const ready = docs.filter((d) => d.status === 'ready' && d.file);
  return {
    docs,
    notices,
    addFiles,
    remove,
    clear,
    files: ready.map((d) => d.file as File),
    isWorking: docs.some((d) => d.status === 'working'),
    isFull: docs.length >= max,
    max,
  };
}
