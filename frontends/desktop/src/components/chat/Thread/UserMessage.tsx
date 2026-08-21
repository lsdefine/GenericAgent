import { memo, useCallback, useRef, useState, useLayoutEffect } from 'react';
import { matchSkillPrefix } from '../Composer/skills';
import { BRIDGE_BASE } from '../../../services/constants';

function fmtSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function iconForExt(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['js', 'ts', 'tsx', 'jsx', 'py', 'rs', 'go', 'c', 'cpp', 'java'].includes(ext)) return '◇';
  if (['json', 'yaml', 'yml', 'toml', 'xml'].includes(ext)) return '{}';
  if (['md', 'txt', 'log', 'csv'].includes(ext)) return '¶';
  if (['pdf'].includes(ext)) return '⊞';
  return '◎';
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleCopy = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  if (typeof navigator === 'undefined' || !navigator.clipboard) return null;

  return (
    <button data-slot="user-bubble-copy" onClick={handleCopy} title={copied ? 'Copied' : 'Copy'}>
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <rect x="5.5" y="5.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.2" />
          <path d="M3.5 10.5v-7a1 1 0 011-1h7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      )}
    </button>
  );
}

interface Props {
  content: string;
  msgId?: string;
  images?: { name: string; path: string }[];
  files?: { name: string; path: string; size?: number }[];
}

export const UserMessage = memo(function UserMessage({ content, msgId, images, files }: Props) {
  const textRef = useRef<HTMLDivElement>(null);
  const [clamped, setClamped] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const expandedRef = useRef(false);
  expandedRef.current = expanded;

  useLayoutEffect(() => {
    const el = textRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      if (!expandedRef.current) {
        setClamped(el.scrollHeight > el.clientHeight + 2);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (!content && (!images || images.length === 0) && (!files || files.length === 0)) return null;

  const skill = matchSkillPrefix(content);

  return (
    <>
      {images && images.length > 0 && (
        <div data-slot="user-images">
          {images.map((img, i) => (
            <img
              key={i}
              data-slot="user-image-thumb"
              src={img.path.startsWith('data:') ? img.path : `${BRIDGE_BASE}/upload/raw?path=${encodeURIComponent(img.path)}`}
              alt={img.name}
            />
          ))}
        </div>
      )}
      {files && files.length > 0 && (
        <div data-slot="user-files">
          {files.map((f, i) => (
            <div key={i} data-slot="user-file-chip">
              <span data-slot="user-file-icon">{iconForExt(f.name)}</span>
              <span data-slot="user-file-name">{f.name}</span>
              {f.size != null && f.size > 0 && <span data-slot="user-file-size">{fmtSize(f.size)}</span>}
            </div>
          ))}
        </div>
      )}
      <div data-slot="aui_user-message-root" id={msgId ? `msg-${msgId}` : undefined} data-msg-id={msgId || undefined} data-role="user">
        <div
          data-slot="user-bubble"
          data-clamped={clamped || undefined}
          data-expanded={expanded || undefined}
        >
          <CopyButton text={content} />
          <div ref={textRef} data-slot="user-bubble-text">
            {skill ? (
              <>
                <span className="skill-chip">/{skill.id}</span>
                {skill.rest && <> {skill.rest}</>}
              </>
            ) : (
              content
            )}
          </div>
          {clamped && (
            <button
              data-slot="user-bubble-expand"
              aria-expanded={expanded}
              aria-label={expanded ? 'Collapse' : 'Expand'}
              onClick={() => setExpanded(v => !v)}
            >
              <svg viewBox="0 0 16 16" fill="none">
                <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </>
  );
});
