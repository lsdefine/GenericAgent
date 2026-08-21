import { useState, useRef, useEffect, useCallback } from 'react';
import { Dropdown, Modal } from '@douyinfe/semi-ui';
import type { SessionInfo } from '../../services/chat';
import { useChatStore } from '../../stores/chat';
import { useI18n } from '../../i18n';
import { Codicon } from '../../lib/icons';

function formatAge(dateVal?: number | string): string {
  if (!dateVal) return '';
  const ts = typeof dateVal === 'number' ? dateVal * 1000 : new Date(dateVal).getTime();
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

export function SessionRow({
  session,
  isActive,
  isWorking,
  onClick,
}: {
  session: SessionInfo;
  isActive: boolean;
  isWorking?: boolean;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const renameSession = useChatStore((s) => s.renameSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const pinSession = useChatStore((s) => s.pinSession);

  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renaming) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming]);

  const handleRenameStart = useCallback(() => {
    setRenameValue(session.title || '');
    setRenaming(true);
    setMenuOpen(false);
  }, [session.title]);

  const handleRenameConfirm = useCallback(() => {
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== session.title) {
      renameSession(session.id, trimmed);
    }
    setRenaming(false);
  }, [renameValue, session.id, session.title, renameSession]);

  const handleRenameCancel = useCallback(() => {
    setRenaming(false);
  }, []);

  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      handleRenameConfirm();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      handleRenameCancel();
    }
  }, [handleRenameConfirm, handleRenameCancel]);

  const handlePin = useCallback(() => {
    setMenuOpen(false);
    setTimeout(() => pinSession(session.id, !session.pinned), 0);
  }, [session.id, session.pinned, pinSession]);

  const handleDelete = useCallback(() => {
    setMenuOpen(false);
    setTimeout(() => {
      Modal.confirm({
        title: t('session.delete'),
        content: t('session.deleteConfirm'),
        okType: 'danger',
        onOk: () => deleteSession(session.id),
      });
    }, 0);
  }, [session.id, deleteSession, t]);

  const menu = (
    <Dropdown.Menu className="ga-session-menu">
      <Dropdown.Item onClick={handleRenameStart}>
        <Codicon name="edit" size="0.875rem" />
        <span>{t('session.rename')}</span>
      </Dropdown.Item>
      <Dropdown.Item onClick={handlePin}>
        <Codicon name="pin" size="0.875rem" />
        <span>{session.pinned ? t('session.unpin') : t('session.pin')}</span>
      </Dropdown.Item>
      <Dropdown.Item type="danger" onClick={handleDelete}>
        <Codicon name="trash" size="0.875rem" />
        <span>{t('session.delete')}</span>
      </Dropdown.Item>
    </Dropdown.Menu>
  );

  return (
    <div
      className={`ga-session-item${isActive ? ' active' : ''}`}
      onClick={renaming || menuOpen ? undefined : onClick}
    >
      <span className="ga-session-content">
        <span className={`ga-status-dot${isWorking ? ' working' : ''}`} />
        {renaming ? (
          <input
            ref={inputRef}
            className="ga-session-rename-input"
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={handleRenameKeyDown}
            onBlur={handleRenameConfirm}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="ga-session-title">
            {session.title || 'Untitled'}
          </span>
        )}
      </span>

      {!renaming && (
        <>
          {session.pinned && (
            <span className="ga-session-pin-icon">
              <Codicon name="pinned" size="0.875rem" />
            </span>
          )}
          <span className="ga-session-age">{formatAge(session.updatedAt)}</span>
          <span
            className={`ga-session-actions${menuOpen ? ' menu-open' : ''}`}
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <Dropdown
              trigger="click"
              position="bottomRight"
              visible={menuOpen}
              onVisibleChange={setMenuOpen}
              render={menu}
            >
              <button
                type="button"
                className="ga-session-actions-btn"
                onClick={(e) => e.stopPropagation()}
                aria-label="Session actions"
              >
                <Codicon name="kebab-vertical" size="0.875rem" />
              </button>
            </Dropdown>
          </span>
        </>
      )}
    </div>
  );
}
