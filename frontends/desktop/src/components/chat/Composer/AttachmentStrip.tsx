import { useCallback } from 'react';

export type AttachmentStatus = 'uploading' | 'ready' | 'error';

export interface AttachmentFile {
  id: string;
  name: string;
  size: number;
  type: 'image' | 'file' | 'url';
  status: AttachmentStatus;
  preview?: string;
  path?: string;
  url?: string;
  errorMsg?: string;
}

interface Props {
  files: AttachmentFile[];
  onRemove: (id: string) => void;
  onRetry?: (id: string) => void;
}

const FILE_ICONS: Record<string, { char: string; color: string }> = {
  pdf: { char: '📄', color: '#E53E3E' },
  doc: { char: '📝', color: '#2B6CB0' },
  docx: { char: '📝', color: '#2B6CB0' },
  xls: { char: '📊', color: '#276749' },
  xlsx: { char: '📊', color: '#276749' },
  csv: { char: '📊', color: '#276749' },
  zip: { char: '📦', color: '#744210' },
  rar: { char: '📦', color: '#744210' },
  py: { char: '🐍', color: '#3182CE' },
  js: { char: '⚡', color: '#D69E2E' },
  ts: { char: '⚡', color: '#3182CE' },
  md: { char: '📋', color: '#4A5568' },
  txt: { char: '📋', color: '#4A5568' },
  json: { char: '{ }', color: '#6366F1' },
};

function getFileIcon(name: string): { char: string; color: string } {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  return FILE_ICONS[ext] || { char: '📎', color: 'var(--semi-color-text-3, #8f959e)' };
}

function fmtSize(bytes: number): string {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function hostname(url: string): string {
  try { return new URL(url).hostname; }
  catch { return url.slice(0, 30); }
}

export function AttachmentStrip({ files, onRemove, onRetry }: Props) {
  const handleRemove = useCallback((id: string) => (e: React.MouseEvent) => {
    e.stopPropagation();
    onRemove(id);
  }, [onRemove]);

  const handleRetry = useCallback((id: string) => (e: React.MouseEvent) => {
    e.stopPropagation();
    onRetry?.(id);
  }, [onRetry]);

  if (files.length === 0) return null;

  return (
    <div data-slot="attachment-strip" data-has-items="">
      {files.map((f) => {
        if (f.type === 'image' && f.preview) {
          return (
            <div key={f.id} data-slot="attachment-thumb" data-status={f.status}>
              <img src={f.preview} alt={f.name} />
              {f.status === 'uploading' && <span data-slot="attachment-spinner" />}
              {f.status === 'error' && (
                <button data-slot="attachment-error-badge" onClick={handleRetry(f.id)} title={f.errorMsg || 'Error'}>!</button>
              )}
              {f.status !== 'uploading' && (
                <button data-slot="attachment-remove" onClick={handleRemove(f.id)} aria-label="Remove">×</button>
              )}
            </div>
          );
        }
        if (f.type === 'url') {
          return (
            <div key={f.id} data-slot="attachment-file-chip" data-status={f.status}>
              <span data-slot="attachment-file-icon">🔗</span>
              <span data-slot="attachment-file-meta">
                <span data-slot="attachment-file-name">{f.url ? hostname(f.url) : f.name}</span>
              </span>
              <button data-slot="attachment-remove" onClick={handleRemove(f.id)} aria-label="Remove">×</button>
            </div>
          );
        }
        const icon = getFileIcon(f.name);
        return (
          <div key={f.id} data-slot="attachment-file-chip" data-status={f.status}>
            {f.status === 'uploading' ? (
              <span data-slot="attachment-spinner" />
            ) : f.status === 'error' ? (
              <button data-slot="attachment-error-badge" onClick={handleRetry(f.id)} title={f.errorMsg || 'Error'}>!</button>
            ) : (
              <span data-slot="attachment-file-icon" style={{ color: icon.color }}>{icon.char}</span>
            )}
            <span data-slot="attachment-file-meta">
              <span data-slot="attachment-file-name">{f.name}</span>
              {f.status === 'error' && f.errorMsg && (
                <span data-slot="attachment-file-error">{f.errorMsg}</span>
              )}
              {f.status !== 'error' && f.size > 0 && (
                <span data-slot="attachment-file-size">{fmtSize(f.size)}</span>
              )}
            </span>
            {f.status !== 'uploading' && (
              <button data-slot="attachment-remove" onClick={handleRemove(f.id)} aria-label="Remove">×</button>
            )}
          </div>
        );
      })}
    </div>
  );
}
