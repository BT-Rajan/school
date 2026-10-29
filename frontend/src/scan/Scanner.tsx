import { type KeyboardEvent, type PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { LanguageSwitch } from "../components";
import { FULL, type Filter, type Point, type Quad } from "./image";
import { assemble, captureFrame, findPage, renderPage } from "./process";
import { clearScan, dropBlobs, getBlob, loadPages, putBlob, savePages, type ScanPage } from "./session";

// FR-D1: a document holds at most 50 pages.
const MAX_PAGES = 50;
const FILTERS: Filter[] = ["enhanced", "bw", "original"];

type View = { kind: "camera" } | { kind: "pages" } | { kind: "edit"; id: string };

/**
 * FR-D3: scanning a paper report with the phone's camera. Pages are taken one after another,
 * each cropped to the sheet's edges, straightened and cleaned up; the supervisor can adjust,
 * reorder and delete them, and the finished pages become one compressed PDF on the device.
 */
export default function Scanner({ onDone, onClose }: { onDone: (file: File) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const [pages, setPages] = useState<ScanPage[] | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [view, setView] = useState<View>({ kind: "camera" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // The latest list, for photos added one after another before the screen redraws.
  const current = useRef<ScanPage[]>([]);

  useEffect(() => {
    void loadPages().then((saved) => {
      current.current = saved;
      setPages(saved);
      if (saved.length) setView({ kind: "pages" });
    });
  }, []);

  // A preview for each finished page.
  useEffect(() => {
    if (!pages) return;
    let live = true;
    void (async () => {
      const next: Record<string, string> = {};
      for (const p of pages) {
        next[p.page] = urls[p.page] ?? URL.createObjectURL(await getBlob(p.page).catch(() => new Blob()));
      }
      if (!live) return;
      for (const [key, url] of Object.entries(urls)) if (!(key in next)) URL.revokeObjectURL(url);
      setUrls(next);
    })();
    return () => {
      live = false;
    };
    // urls is read only to reuse previews already made.
  }, [pages]);

  const update = useCallback(async (next: ScanPage[]) => {
    current.current = next;
    setPages(next);
    await savePages(next);
  }, []);

  const addPhoto = async (photo: Blob) => {
    if (current.current.length >= MAX_PAGES) return;
    setBusy(true);
    setProblem(null);
    try {
      const quad = await findPage(photo);
      const adjustments = { quad, filter: "enhanced" as Filter, turns: 0 };
      const page = await renderPage(photo, adjustments);
      const item: ScanPage = { id: crypto.randomUUID?.() ?? String(Date.now()), photo: await putBlob(photo), page: await putBlob(page), ...adjustments };
      await update([...current.current, item]);
    } catch {
      setProblem(t("scan.photoFailed"));
    } finally {
      setBusy(false);
    }
  };

  const move = (i: number, delta: number) => {
    if (!pages) return;
    const j = i + delta;
    if (j < 0 || j >= pages.length) return;
    const next = [...pages];
    [next[i], next[j]] = [next[j], next[i]];
    void update(next);
  };

  const remove = async (page: ScanPage) => {
    if (!pages) return;
    await update(pages.filter((p) => p.id !== page.id));
    await dropBlobs(page.photo, page.page);
  };

  const finish = async () => {
    if (!pages?.length) return;
    setBusy(true);
    try {
      const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
      const file = await assemble(await Promise.all(pages.map((p) => getBlob(p.page))), `scan-${stamp}.pdf`);
      onDone(file);
      await clearScan(pages);
      onClose();
    } catch {
      setProblem(t("scan.assembleFailed"));
      setBusy(false);
    }
  };

  const discard = async () => {
    if (pages?.length && !window.confirm(t("scan.confirmDiscard"))) return;
    if (pages) await clearScan(pages);
    onClose();
  };

  if (!pages) return null;
  const editing = view.kind === "edit" ? pages.find((p) => p.id === view.id) : undefined;

  return (
    <div className="scanner" role="dialog" aria-modal="true" aria-label={t("scan.title")}>
      <div className="scanner-head">
        <h2>{t("scan.title")}</h2>
        <span className="hint">{t("scan.pageCount", { count: pages.length })}</span>
        <div className="page-actions">
          <LanguageSwitch />
          {/* Closing keeps the pages on the device; the scan carries on next time. */}
          <button type="button" className="link" onClick={onClose} aria-label={t("common.close")}>✕</button>
        </div>
      </div>
      {problem && <div className="alert alert-error" role="alert">{problem}</div>}
      {view.kind === "camera" && (
        <Camera
          busy={busy}
          full={pages.length >= MAX_PAGES}
          count={pages.length}
          last={pages.length ? urls[pages[pages.length - 1].page] : undefined}
          onPhoto={addPhoto}
          onPages={() => setView({ kind: "pages" })}
        />
      )}
      {view.kind === "pages" && (
        <div className="scanner-body">
          {pages.length === 0 && <p className="hint">{t("scan.noPages")}</p>}
          <ol className="scan-pages">
            {pages.map((p, i) => (
              <li key={p.id}>
                <button type="button" className="scan-thumb" onClick={() => setView({ kind: "edit", id: p.id })}
                  aria-label={t("scan.adjustPage", { n: i + 1 })}>
                  {urls[p.page] && <img src={urls[p.page]} alt="" />}
                  <span className="scan-number">{i + 1}</span>
                </button>
                <span className="row-actions">
                  <button type="button" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("builder.moveUp")}>↑</button>
                  <button type="button" disabled={i === pages.length - 1} onClick={() => move(i, 1)} aria-label={t("builder.moveDown")}>↓</button>
                  <button type="button" className="link" onClick={() => void remove(p)}>{t("builder.remove")}</button>
                </span>
              </li>
            ))}
          </ol>
          <div className="page-actions">
            <button type="button" disabled={pages.length >= MAX_PAGES} onClick={() => setView({ kind: "camera" })}>
              {t("scan.addPages")}
            </button>
            <button type="button" className="primary" disabled={busy || !pages.length} onClick={() => void finish()}>
              {busy ? t("scan.assembling") : t("scan.usePages")}
            </button>
            <button type="button" className="link danger" onClick={() => void discard()}>{t("scan.discard")}</button>
          </div>
        </div>
      )}
      {editing && (
        <Editor
          key={editing.id}
          page={editing}
          onCancel={() => setView({ kind: "pages" })}
          onSave={async (changes) => {
            const photo = await getBlob(editing.photo);
            const rendered = await putBlob(await renderPage(photo, changes));
            await update(pages.map((p) => (p.id === editing.id ? { ...p, ...changes, page: rendered } : p)));
            await dropBlobs(editing.page);
            setView({ kind: "pages" });
          }}
        />
      )}
    </div>
  );
}

function Camera({
  busy,
  full,
  count,
  last,
  onPhoto,
  onPages,
}: {
  busy: boolean;
  full: boolean;
  count: number;
  last?: string;
  onPhoto: (blob: Blob) => Promise<void>;
  onPages: () => void;
}) {
  const { t } = useTranslation();
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"starting" | "live" | "unavailable">("starting");

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    void (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera");
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 3264 }, height: { ideal: 2448 } },
          audio: false,
        });
        if (stopped) return stream.getTracks().forEach((track) => track.stop());
        video.current!.srcObject = stream;
        await video.current!.play();
        setState("live");
      } catch {
        // No permission or no camera: the phone's own camera app, through the file picker, still works.
        setState("unavailable");
      }
    })();
    return () => {
      stopped = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <div className="scanner-body scanner-camera">
      <video ref={video} playsInline muted hidden={state !== "live"} />
      {state === "starting" && <p className="hint">{t("scan.starting")}</p>}
      {state === "unavailable" && <p className="hint">{t("scan.noCamera")}</p>}
      {full && <p className="hint">{t("scan.full", { max: MAX_PAGES })}</p>}
      <div className="scanner-controls">
        <button type="button" className="scan-thumb small" onClick={onPages} disabled={!count} aria-label={t("scan.reviewPages")}>
          {last && <img src={last} alt="" />}
          <span className="scan-number">{count}</span>
        </button>
        {state === "live" ? (
          <button type="button" className="primary shutter" disabled={busy || full}
            onClick={() => void captureFrame(video.current!).then(onPhoto)}>
            {busy ? t("scan.working") : t("scan.capture")}
          </button>
        ) : (
          <label className={`button-like primary shutter${busy || full ? " disabled" : ""}`}>
            {busy ? t("scan.working") : t("scan.takePhoto")}
            <input type="file" className="visually-hidden" accept="image/*" capture="environment" disabled={busy || full}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void onPhoto(f); }} />
          </label>
        )}
        <label className={`button-like${busy || full ? " disabled" : ""}`}>
          {t("scan.fromPhotos")}
          <input type="file" className="visually-hidden" accept="image/*" multiple disabled={busy || full}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              void (async () => {
                for (const f of files) await onPhoto(f);
              })();
            }} />
        </label>
        <button type="button" onClick={onPages} disabled={!count}>{t("scan.done")}</button>
      </div>
    </div>
  );
}

function Editor({ page, onSave, onCancel }: { page: ScanPage; onSave: (changes: Pick<ScanPage, "quad" | "filter" | "turns">) => Promise<void>; onCancel: () => void }) {
  const { t } = useTranslation();
  const [quad, setQuad] = useState<Quad>(page.quad);
  const [filter, setFilter] = useState<Filter>(page.filter);
  const [turns, setTurns] = useState(page.turns);
  const [url, setUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const dragging = useRef<number | null>(null);

  useEffect(() => {
    let made: string | null = null;
    void getBlob(page.photo).then((blob) => setUrl((made = URL.createObjectURL(blob))));
    return () => {
      if (made) URL.revokeObjectURL(made);
    };
  }, [page.photo]);

  const setCorner = (i: number, p: Point) =>
    setQuad((q) => q.map((c, j) => (j === i ? { x: Math.min(1, Math.max(0, p.x)), y: Math.min(1, Math.max(0, p.y)) } : c)) as Quad);
  const pointAt = (e: PointerEvent) => {
    const box = frame.current!.getBoundingClientRect();
    return { x: (e.clientX - box.left) / box.width, y: (e.clientY - box.top) / box.height };
  };
  const onKey = (i: number, e: KeyboardEvent) => {
    const step = e.shiftKey ? 0.05 : 0.01;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (!d) return;
    e.preventDefault();
    setCorner(i, { x: quad[i].x + d[0], y: quad[i].y + d[1] });
  };
  const corners = [t("scan.corners.topLeft"), t("scan.corners.topRight"), t("scan.corners.bottomRight"), t("scan.corners.bottomLeft")];

  return (
    <div className="scanner-body">
      <p className="hint">{t("scan.adjustHint")}</p>
      {/* The photo is not mirrored in Arabic: the corners are where they are on the paper. */}
      <div className="scan-frame" dir="ltr" ref={frame}
        onPointerMove={(e) => dragging.current !== null && setCorner(dragging.current, pointAt(e))}
        onPointerUp={() => (dragging.current = null)}
        onPointerCancel={() => (dragging.current = null)}>
        {url && <img src={url} alt={t("scan.photoAlt")} draggable={false} />}
        <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
          <polygon points={quad.map((c) => `${c.x},${c.y}`).join(" ")} />
        </svg>
        {quad.map((c, i) => (
          <button key={i} type="button" className="scan-corner" style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%` }}
            aria-label={corners[i]}
            onKeyDown={(e) => onKey(i, e)}
            onPointerDown={(e) => {
              dragging.current = i;
              (e.currentTarget.parentElement as HTMLElement).setPointerCapture(e.pointerId);
            }} />
        ))}
      </div>
      <div className="page-actions">
        <button type="button" onClick={() => setQuad(FULL)}>{t("scan.wholePhoto")}</button>
        <button type="button" onClick={() => void getBlob(page.photo).then(findPage).then(setQuad)}>{t("scan.findEdges")}</button>
        <button type="button" onClick={() => setTurns((n) => (n + 1) % 4)}>{t("scan.rotate")}</button>
      </div>
      <fieldset className="field">
        <legend>{t("scan.look")}</legend>
        {FILTERS.map((f) => (
          <label key={f} className="check">
            <input type="radio" name="scan-filter" checked={filter === f} onChange={() => setFilter(f)} /> {t(`scan.filters.${f}`)}
          </label>
        ))}
      </fieldset>
      {turns > 0 && <p className="hint">{t("scan.turned", { degrees: turns * 90 })}</p>}
      <div className="page-actions">
        <button type="button" className="primary" disabled={saving}
          onClick={() => {
            setSaving(true);
            void onSave({ quad, filter, turns }).finally(() => setSaving(false));
          }}>
          {saving ? t("scan.working") : t("scan.applyPage")}
        </button>
        <button type="button" onClick={onCancel}>{t("common.cancel")}</button>
      </div>
    </div>
  );
}
