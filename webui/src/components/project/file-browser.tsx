"use client";

import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  MoveLeft,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Tree, type NodeRendererProps, type TreeApi } from "react-arborist";

import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";
import type { FileEntry, FileListing } from "@/lib/types";

type FileTreeNode = {
  id: string;
  path: string;
  name: string;
  type: "dir" | "file";
  ext?: string;
  children?: FileTreeNode[];
  loaded?: boolean;
};

const TEXT_PREVIEW_EXTENSIONS = new Set([
  ".md",
  ".txt",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".py",
  ".sh",
  ".tex",
  ".bib",
  ".csv",
  ".log",
  ".marker",
]);

function buildTreeNodes(
  dirPath: string,
  cache: Record<string, FileListing>,
  index: Map<string, FileTreeNode>,
): FileTreeNode[] {
  const listing = cache[dirPath];
  if (!listing) return [];

  const dirs = listing.dirs.map((dir) => {
    const node: FileTreeNode = {
      id: dir.path,
      path: dir.path,
      name: dir.name,
      type: "dir",
      loaded: Boolean(cache[dir.path]),
      children: buildTreeNodes(dir.path, cache, index),
    };
    index.set(node.id, node);
    return node;
  });

  const files = listing.files.map((file) => {
    const node: FileTreeNode = {
      id: file.path,
      path: file.path,
      name: file.name,
      type: "file",
      ext: file.ext,
    };
    index.set(node.id, node);
    return node;
  });

  return [...dirs, ...files];
}

function inferPreviewKind(entry: FileEntry | null) {
  if (!entry) return "empty" as const;
  if (entry.ext?.toLowerCase() === ".pdf") return "pdf" as const;
  if (entry.ext && TEXT_PREVIEW_EXTENSIONS.has(entry.ext.toLowerCase())) return "text" as const;
  return "unsupported" as const;
}

function getParentDirectory(path: string) {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

export function FileBrowser({ project }: { project: string }) {
  const { t } = useI18n();
  const treeRef = useRef<TreeApi<FileTreeNode> | null>(null);
  const treeViewportRef = useRef<HTMLDivElement | null>(null);

  const [currentDir, setCurrentDir] = useState("");
  const [treeCache, setTreeCache] = useState<Record<string, FileListing>>({});
  const [loadingDirs, setLoadingDirs] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<FileEntry | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [treeHeight, setTreeHeight] = useState(520);

  const loadDirectory = useCallback(
    async (dir: string) => {
      setLoadingDirs((prev) => {
        const next = new Set(prev);
        next.add(dir);
        return next;
      });

      try {
        const nextListing = await api.getFiles(project, dir);
        setTreeCache((prev) => ({ ...prev, [dir]: nextListing }));
        setError(null);
      } catch (nextError) {
        if (dir === currentDir) {
          setError(nextError instanceof Error ? nextError.message : t("loadFilesFailed"));
        }
      } finally {
        setLoadingDirs((prev) => {
          const next = new Set(prev);
          next.delete(dir);
          return next;
        });
      }
    },
    [currentDir, project, t],
  );

  useEffect(() => {
    setCurrentDir("");
    setTreeCache({});
    setLoadingDirs(new Set());
    setSelectedFile(null);
    setPreview("");
    setError(null);
  }, [project]);

  useEffect(() => {
    if (treeCache[currentDir]) return;
    void loadDirectory(currentDir);
  }, [currentDir, loadDirectory, treeCache]);

  useEffect(() => {
    const node = treeViewportRef.current;
    if (!node) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setTreeHeight(Math.max(320, Math.floor(entry.contentRect.height)));
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedFile) return;
    if (inferPreviewKind(selectedFile) !== "text") return;

    const nextPath = selectedFile.path;
    let cancelled = false;
    setPreview("");

    async function loadPreview() {
      try {
        const content = await api.getFile(project, nextPath);
        if (!cancelled) {
          setPreview(content);
        }
      } catch (nextError) {
        if (!cancelled) {
          setPreview(nextError instanceof Error ? nextError.message : t("loadFileFailed"));
        }
      }
    }

    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [project, selectedFile, t]);

  const pathSegments = useMemo(() => currentDir.split("/").filter(Boolean), [currentDir]);

  const breadcrumbs = useMemo(() => {
    const items = [{ label: t("root"), path: "" }];
    let assembled = "";
    for (const segment of pathSegments) {
      assembled = assembled ? `${assembled}/${segment}` : segment;
      items.push({ label: segment, path: assembled });
    }
    return items;
  }, [pathSegments, t]);

  const listing = treeCache[currentDir] || null;
  const parentDir = pathSegments.slice(0, -1).join("/");

  const { treeData, nodeIndex } = useMemo(() => {
    const index = new Map<string, FileTreeNode>();
    return {
      treeData: buildTreeNodes("", treeCache, index),
      nodeIndex: index,
    };
  }, [treeCache]);

  const ensureDirectoryLoaded = useCallback(
    (path: string) => {
      if (!treeCache[path]) {
        void loadDirectory(path);
      }
    },
    [loadDirectory, treeCache],
  );

  const selectDirectory = useCallback(
    (path: string) => {
      setCurrentDir(path);
      ensureDirectoryLoaded(path);
      if (path) {
        treeRef.current?.openParents(path);
        treeRef.current?.open(path);
        treeRef.current?.select(path);
      }
    },
    [ensureDirectoryLoaded],
  );

  const handleToggle = useCallback(
    (id: string) => {
      const node = nodeIndex.get(id);
      if (node?.type === "dir" && !node.loaded) {
        ensureDirectoryLoaded(node.path);
      }
    },
    [ensureDirectoryLoaded, nodeIndex],
  );

  const selectedPreviewKind = inferPreviewKind(selectedFile);
  const previewLabel = selectedFile?.path || t("selectFilePreview");
  const previewUrl = selectedFile ? api.getFileUrl(project, selectedFile.path) : null;

  function FileTreeNodeRenderer({ node, style }: NodeRendererProps<FileTreeNode>) {
    const isDirectory = node.data.type === "dir";
    const isActiveDirectory = isDirectory && currentDir === node.data.path;
    const isActiveFile = !isDirectory && selectedFile?.path === node.data.path;
    const isActive = isActiveDirectory || isActiveFile;
    const isLoading = isDirectory && loadingDirs.has(node.data.path) && !node.data.loaded;

    return (
      <div style={style} className="group">
        <div
          className={`mx-1 my-1 flex h-[calc(100%-8px)] items-center rounded-[18px] border transition ${
            isActive
              ? "border-orange-300 bg-orange-50 text-orange-900"
              : "border-stone-200 bg-white/75 text-stone-800 hover:border-orange-300 hover:bg-orange-50"
          }`}
        >
          {isDirectory ? (
            <button
              type="button"
              onClick={() => node.toggle()}
              className="ml-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-stone-500 transition hover:bg-white/80 hover:text-stone-900"
              aria-label={node.isOpen ? `Collapse ${node.data.name}` : `Expand ${node.data.name}`}
            >
              {node.isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          ) : (
            <span className="ml-4 mr-2 h-9 w-5 shrink-0" />
          )}

          <button
            type="button"
            onClick={() => {
              if (isDirectory) {
                selectDirectory(node.data.path);
              } else {
                const parentPath = getParentDirectory(node.data.path);
                setCurrentDir(parentPath);
                ensureDirectoryLoaded(parentPath);
                treeRef.current?.openParents(node.data.path);
                treeRef.current?.select(node.data.path);
                setSelectedFile({
                  name: node.data.name,
                  path: node.data.path,
                  type: "file",
                  ext: node.data.ext,
                });
              }
            }}
            className="flex min-w-0 flex-1 items-center gap-3 py-2.5 pr-4 text-left"
          >
            {isDirectory ? (
              <FolderOpen className="h-4 w-4 shrink-0 text-orange-700" />
            ) : (
              <FileText className="h-4 w-4 shrink-0" />
            )}
            <div className="min-w-0">
              <div className="truncate">{node.data.name}</div>
              {!isDirectory && node.data.ext ? (
                <div className="mt-0.5 text-xs uppercase tracking-[0.18em] text-stone-500">
                  {node.data.ext.replace(/^\./, "")}
                </div>
              ) : isLoading ? (
                <div className="mt-0.5 text-xs uppercase tracking-[0.18em] text-stone-500">
                  {t("refreshing")}
                </div>
              ) : null}
            </div>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(300px,0.74fr)_minmax(0,1.26fr)]">
      <div className="panel-surface flex h-[68vh] flex-col overflow-hidden rounded-[24px] p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="eyebrow">{t("workspace")}</div>
            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[0.95rem] text-stone-700">
              {breadcrumbs.map((crumb, index) => (
                <div key={crumb.path || "root"} className="flex items-center gap-2">
                  {index > 0 ? <ChevronRight className="h-4 w-4 text-stone-400" /> : null}
                  <button
                    type="button"
                    onClick={() => selectDirectory(crumb.path)}
                    className={`rounded-full px-2.5 py-1.5 transition ${
                      crumb.path === currentDir
                        ? "bg-orange-100 text-orange-900"
                        : "bg-white/70 text-stone-600 hover:bg-white hover:text-stone-900"
                    }`}
                  >
                    {crumb.label}
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">
              {t("currentDirectory")}
            </div>
            <div className="mt-2 text-sm text-stone-700">{currentDir || t("root")}</div>
          </div>
        </div>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => selectDirectory(parentDir)}
            disabled={!currentDir}
            className="status-chip inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[0.72rem] text-stone-600 disabled:cursor-not-allowed disabled:opacity-45"
          >
            <MoveLeft className="h-4 w-4" />
            {t("upLevel")}
          </button>
          <div className="text-[0.68rem] uppercase tracking-[0.18em] text-stone-500">
            {t("folderSummary", {
              dirs: listing?.dirs.length || 0,
              files: listing?.files.length || 0,
            })}
          </div>
        </div>

        {error ? <div className="mb-3 text-sm text-red-600">{error}</div> : null}

        <div ref={treeViewportRef} className="min-h-0 flex-1 overflow-hidden rounded-[18px] border border-stone-200 bg-white/45">
          {!treeCache[""] && loadingDirs.has("") ? (
            <div className="flex h-full items-center justify-center px-4 text-sm text-stone-500">
              {t("refreshing")}
            </div>
          ) : treeData.length === 0 ? (
            <div className="flex h-full items-center justify-center px-4 text-sm text-stone-500">
              {t("emptyDirectory")}
            </div>
          ) : (
            <Tree<FileTreeNode>
              ref={treeRef}
              data={treeData}
              width="100%"
              height={treeHeight}
              rowHeight={64}
              indent={22}
              padding={8}
              overscanCount={8}
              selection={selectedFile?.path || currentDir || undefined}
              openByDefault={false}
              disableDrag
              disableEdit
              onToggle={handleToggle}
            >
              {FileTreeNodeRenderer}
            </Tree>
          )}
        </div>
      </div>

      <div className="panel-dark flex h-[68vh] min-h-0 flex-col overflow-hidden rounded-[24px] p-4">
        <div className="mb-3 flex shrink-0 items-start justify-between gap-3">
          <div className="text-[0.68rem] uppercase tracking-[0.22em] text-stone-400">
            {t("preview")}
          </div>
          <div className="max-w-[70%] truncate text-right text-[0.92rem] text-stone-300">
            {previewLabel}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden rounded-[20px] border border-white/10 bg-black/20">
          {selectedPreviewKind === "pdf" && previewUrl ? (
            <iframe
              src={previewUrl}
              title={selectedFile?.name || "PDF preview"}
              className="h-full w-full bg-white"
            />
          ) : selectedPreviewKind === "text" ? (
            <pre className="h-full overflow-auto whitespace-pre-wrap break-words px-4 py-4 text-sm leading-7 text-stone-100">
              {selectedFile ? preview || t("loadingPreview") : t("selectFilePreview")}
            </pre>
          ) : selectedPreviewKind === "unsupported" ? (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm leading-7 text-stone-300">
              {t("previewUnavailable")}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm leading-7 text-stone-300">
              {t("selectFilePreview")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
