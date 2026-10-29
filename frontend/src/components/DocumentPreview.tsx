import { Download, FileText } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState, Spinner } from "@/components/ui/Feedback";
import { fetchDocument, fetchPreview } from "@/lib/api";

/**
 * Pages are rendered to images by the API, so the preview looks the same in every browser and needs no
 * PDF plug-in. Both requests carry the bearer token, so they are fetched as blobs.
 */
export function DocumentPreview({ invoiceId, fileName }: { invoiceId: string; fileName: string }) {
  const [pages, setPages] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    (async () => {
      try {
        const first = await fetchPreview(invoiceId, 1);
        const rest = await Promise.all(
          Array.from({ length: Math.min(first.pages, 10) - 1 }, (_, i) => fetchPreview(invoiceId, i + 2)),
        );
        for (const { blob } of [first, ...rest]) urls.push(URL.createObjectURL(blob));
        if (!cancelled) setPages([...urls]);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Preview unavailable");
      }
    })();
    return () => {
      cancelled = true;
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [invoiceId]);

  const download = async () => {
    setDownloading(true);
    try {
      const url = URL.createObjectURL(await fetchDocument(invoiceId));
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
        <div className="flex min-w-0 items-center gap-2 text-[13px] text-ink-2">
          <FileText className="size-4 shrink-0 text-ink-3" aria-hidden />
          <span className="truncate">{fileName}</span>
          {pages.length > 1 && <span className="text-ink-3">· {pages.length} pages</span>}
        </div>
        <Button size="sm" variant="ghost" icon={<Download className="size-3.5" />} loading={downloading} onClick={() => void download()}>
          Original
        </Button>
      </div>
      <div className="max-h-[calc(100vh-11rem)] overflow-y-auto bg-surface-hover p-4">
        {error && <EmptyState icon={FileText} title="Preview unavailable">{error}</EmptyState>}
        {!error && pages.length === 0 && (
          <div className="grid aspect-[1/1.414] place-items-center rounded-md bg-surface">
            <Spinner label="Rendering document" />
          </div>
        )}
        <div className="space-y-4">
          {pages.map((url, index) => (
            <img
              key={url}
              src={url}
              alt={`${fileName}, page ${index + 1}`}
              className="w-full rounded-sm bg-white shadow-card ring-1 ring-line"
            />
          ))}
        </div>
      </div>
    </div>
  );
}
