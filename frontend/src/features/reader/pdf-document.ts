import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist';

/**
 * PDF drawing, from this application's own files: no remote worker, fonts or character maps.
 * Only the page's own drawing is rendered. Annotations are off, so links, form fields and
 * attachments do nothing, and a PDF's scripts are never run.
 */
const MAX_IMAGE_PIXELS = 64_000_000;
const MAX_CANVAS_PIXELS = 16_000_000;
const ANNOTATIONS_OFF = 0;

async function library() {
  const pdfjs = await import('pdfjs-dist');
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url,
  ).toString();
  return pdfjs;
}

export async function openPdf(url: string): Promise<PDFDocumentLoadingTask> {
  const pdfjs = await library();
  return pdfjs.getDocument({
    url,
    isEvalSupported: false,
    enableXfa: false,
    disableAutoFetch: true,
    stopAtErrors: false,
    maxImageSize: MAX_IMAGE_PIXELS,
    cMapUrl: '/pdfjs/cmaps/',
    cMapPacked: true,
    standardFontDataUrl: '/pdfjs/standard_fonts/',
  });
}

/** Draws one page. Returns a cancel for a page that scrolled or turned away first. */
export function drawPage(
  document: PDFDocumentProxy,
  number: number,
  canvas: HTMLCanvasElement,
  wantedWidth: number,
  onDone: (error: unknown) => void,
): () => void {
  let cancelled = false;
  let stop: (() => void) | undefined;
  void document
    .getPage(number)
    .then((page) => {
      if (cancelled) return undefined;
      const base = page.getViewport({ scale: 1 });
      const fitted = Math.max(wantedWidth, 1) / base.width;
      const bound = Math.sqrt(MAX_CANVAS_PIXELS / (base.width * base.height));
      const viewport = page.getViewport({ scale: Math.min(fitted, bound) });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const task = page.render({ canvas, viewport, annotationMode: ANNOTATIONS_OFF });
      stop = () => task.cancel();
      return task.promise;
    })
    .then(() => {
      if (!cancelled) onDone(null);
    })
    .catch((error: unknown) => {
      if (!cancelled) onDone(error);
    });
  return () => {
    cancelled = true;
    stop?.();
  };
}
