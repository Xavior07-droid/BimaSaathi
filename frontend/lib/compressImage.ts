// Client-side image compression for claim documents (F18).
// Phone photos are often 4-10 MB. We shrink them in the browser before upload so the free
// Render server receives less data and Gemini vision gets a sensible size. Nothing leaves the device here.

export const MAX_DIMENSION = 1600; // px, longest side: still readable for stamps and small print
export const JPEG_QUALITY = 0.8;
const SKIP_BELOW_BYTES = 300 * 1024; // already small: keep the original untouched

/** Scale (w, h) down so the longest side is <= max. Never scales up. Pure, easy to test. */
export function fitWithin(w: number, h: number, max: number): { width: number; height: number } {
  const longest = Math.max(w, h);
  if (longest <= max) return { width: w, height: h };
  const scale = max / longest;
  return { width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) };
}

interface Decoded {
  source: CanvasImageSource;
  width: number;
  height: number;
  release: () => void;
}

async function decode(file: File): Promise<Decoded> {
  // createImageBitmap honours the EXIF orientation of phone photos (no sideways pictures).
  if (typeof createImageBitmap === 'function') {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      return { source: bmp, width: bmp.width, height: bmp.height, release: () => bmp.close() };
    } catch {
      /* fall through to the <img> path */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    await img.decode();
    return { source: img, width: img.naturalWidth, height: img.naturalHeight, release: () => URL.revokeObjectURL(url) };
  } catch (e) {
    URL.revokeObjectURL(url);
    throw e;
  }
}

const toBlob = (canvas: HTMLCanvasElement, quality: number) =>
  new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));

/**
 * Returns a smaller JPEG File, or the original when it is already small / compression would not help.
 * Throws if the browser cannot decode the image (corrupt file, unsupported format).
 */
export async function compressImage(file: File): Promise<File> {
  const img = await decode(file);
  try {
    if (!img.width || !img.height) throw new Error('empty image');
    const { width, height } = fitWithin(img.width, img.height, MAX_DIMENSION);
    const resized = width !== img.width || height !== img.height;
    if (!resized && file.size <= SKIP_BELOW_BYTES) return file;

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;
    ctx.fillStyle = '#ffffff'; // PNGs may be transparent; JPEG has no alpha
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img.source, 0, 0, width, height);

    const blob = await toBlob(canvas, JPEG_QUALITY);
    canvas.width = canvas.height = 0; // free the pixel buffer (matters on low-RAM phones)
    if (!blob || (blob.size >= file.size && !resized)) return file;

    const base = file.name.replace(/\.[^.]+$/, '') || 'document';
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg', lastModified: Date.now() });
  } finally {
    img.release();
  }
}
