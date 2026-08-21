import { useChatStore } from '../../../stores/chat';
import { useSettingsStore } from '../../../stores/settings';

const LABELS = {
  thinking: { zh: '思考中…', en: 'Thinking…' },
  queued: { zh: '排队中', en: 'Queued' },
};

export function StatusStack() {
  const isGenerating = useChatStore((s) => s.status === 'running');
  const queue = useChatStore((s) => s.pendingQueue);
  const cancelQueued = useChatStore((s) => s.cancelQueued);
  const lang = useSettingsStore((s) => s.lang);

  if (!isGenerating && queue.length === 0) return null;

  const t = (key: keyof typeof LABELS) => LABELS[key][lang] || LABELS[key].en;

  return (
    <div data-slot="composer-status-stack">
      {isGenerating && (
        <div data-slot="status-running">
          <span data-slot="status-dot" />
          <span data-slot="status-label">{t('thinking')}</span>
        </div>
      )}
      {queue.map((item, i) => (
        <div key={i} data-slot="status-queued">
          <span data-slot="status-queue-num">#{i + 1}</span>
          <span data-slot="status-queue-text">{item.text.slice(0, 40)}{item.text.length > 40 ? '…' : ''}</span>
          <button data-slot="status-queue-cancel" onClick={() => cancelQueued(i)} aria-label="Cancel">
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
