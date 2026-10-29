import { clsx } from "clsx";
import { CircleCheck, CircleX, FileUp, Loader2, TriangleAlert } from "lucide-react";
import { useCallback, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ApiError } from "@/lib/api";
import { useUpload } from "@/lib/queries";

type ItemState =
  | { state: "uploading" }
  | { state: "queued"; id: string }
  | { state: "duplicate"; id: string; message: string }
  | { state: "error"; message: string };

interface UploadItem {
  key: string;
  file: File;
  status: ItemState;
}

const ACCEPT = "application/pdf,image/png,image/jpeg";
const MAX_BYTES = 15 * 1024 * 1024;

export function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const upload = useUpload();

  const update = (key: string, status: ItemState) =>
    setItems((current) => current.map((item) => (item.key === key ? { ...item, status } : item)));

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const key = `${file.name}-${file.size}-${crypto.randomUUID()}`;
        if (file.size > MAX_BYTES) {
          setItems((current) => [...current, { key, file, status: { state: "error", message: "Larger than 15 MB" } }]);
          continue;
        }
        setItems((current) => [...current, { key, file, status: { state: "uploading" } }]);
        upload
          .mutateAsync(file)
          .then((invoice) => update(key, { state: "queued", id: invoice.id }))
          .catch((error: unknown) => {
            if (error instanceof ApiError && error.status === 409 && typeof error.extra.invoice_id === "string") {
              update(key, { state: "duplicate", id: error.extra.invoice_id, message: error.message });
            } else {
              update(key, { state: "error", message: error instanceof Error ? error.message : "Upload failed" });
            }
          });
      }
    },
    [upload],
  );

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  };

  const close = () => {
    onClose();
    setItems([]);
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Upload invoices"
      description="PDF, PNG or JPEG up to 15 MB. Each document is extracted, matched against the ERP and scored automatically."
      footer={<Button onClick={close}>{items.length ? "Done" : "Cancel"}</Button>}
    >
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "flex flex-col items-center rounded-xl border border-dashed px-6 py-8 text-center transition-colors",
          dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2",
        )}
      >
        <FileUp className="mb-2 size-6 text-ink-3" aria-hidden />
        <p className="text-sm font-medium text-ink">Drop invoice files here</p>
        <p className="mt-1 text-[13px] text-ink-3">or</p>
        <Button size="sm" className="mt-2" onClick={() => input.current?.click()}>
          Browse files
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          className="sr-only"
          data-testid="upload-input"
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {items.length > 0 && (
        <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
          {items.map(({ key, file, status }) => (
            <li key={key} className="flex items-center gap-3 px-3 py-2.5 text-[13px]">
              {status.state === "uploading" && <Loader2 className="size-4 shrink-0 animate-spin text-ink-3" />}
              {status.state === "queued" && <CircleCheck className="size-4 shrink-0 text-good" />}
              {status.state === "duplicate" && <TriangleAlert className="size-4 shrink-0 text-warning" />}
              {status.state === "error" && <CircleX className="size-4 shrink-0 text-critical" />}
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-ink">{file.name}</div>
                <div className="text-ink-3">
                  {status.state === "uploading" && "Uploading…"}
                  {status.state === "queued" && "Queued for processing"}
                  {status.state === "duplicate" && "Already uploaded"}
                  {status.state === "error" && status.message}
                </div>
              </div>
              {(status.state === "queued" || status.state === "duplicate") && (
                <Link to={`/invoices/${status.id}`} onClick={close} className="font-medium text-accent-ink hover:underline">
                  View
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
