import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useNotificationStore, type AppNotification } from '../../stores/notifications';
import { IconClose } from '@douyinfe/semi-icons';
import './notifications.css';

function NotificationItem({ item, onDismiss }: { item: AppNotification; onDismiss: () => void }) {
  const isError = item.kind === 'error' || item.kind === 'warning';

  return (
    <div className={`ga-notification ga-notification--${item.kind}`} role="alert">
      <div className="ga-notification-body">
        {item.title && <div className="ga-notification-title">{item.title}</div>}
        <div className="ga-notification-message">{item.message}</div>
        {item.action && (
          <button className="ga-notification-action" onClick={item.action.onClick}>
            {item.action.label}
          </button>
        )}
      </div>
      {isError && (
        <button className="ga-notification-dismiss" onClick={onDismiss} aria-label="close">
          <IconClose size="small" />
        </button>
      )}
    </div>
  );
}

export function NotificationStack() {
  const items = useNotificationStore((s) => s.items);
  const dismiss = useNotificationStore((s) => s.dismiss);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      const el = document.createElement('div');
      el.id = 'ga-notification-portal';
      document.body.appendChild(el);
      containerRef.current = el;
    }
    return () => {
      if (containerRef.current) {
        document.body.removeChild(containerRef.current);
        containerRef.current = null;
      }
    };
  }, []);

  if (!containerRef.current || items.length === 0) return null;

  const errors = items.filter((i) => i.kind === 'error' || i.kind === 'warning');
  const infos = items.filter((i) => i.kind === 'info' || i.kind === 'success');

  return createPortal(
    <>
      {errors.length > 0 && (
        <div className="ga-notification-stack ga-notification-stack--top">
          {errors.map((item) => (
            <NotificationItem key={item.id} item={item} onDismiss={() => dismiss(item.id)} />
          ))}
        </div>
      )}
      {infos.length > 0 && (
        <div className="ga-notification-stack ga-notification-stack--bottom">
          {infos.map((item) => (
            <NotificationItem key={item.id} item={item} onDismiss={() => dismiss(item.id)} />
          ))}
        </div>
      )}
    </>,
    containerRef.current,
  );
}
