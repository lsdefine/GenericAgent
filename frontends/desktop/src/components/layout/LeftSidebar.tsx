import { useState } from 'react';
import { Input } from '@douyinfe/semi-ui';
import { IconSearchStroked } from '@douyinfe/semi-icons';
import { Codicon } from '../../lib/icons';
import { useAppStore, type PageId } from '../../stores/app';
import { useSettingsStore } from '../../stores/settings';
import { useChatStore } from '../../stores/chat';
import { useI18n } from '../../i18n';
import { SessionSectionHeader } from './SessionSectionHeader';
import { SessionRow } from './SessionRow';

const NAV_ITEMS: { key: PageId; icon: string; textKey: string }[] = [
  { key: 'services', icon: 'symbol-misc', textKey: 'nav.services' },
  { key: 'collab', icon: 'robot', textKey: 'nav.collab' },
  { key: 'token', icon: 'graph', textKey: 'nav.token' },
];

export function LeftSidebar() {
  const { activePage, setPage } = useAppStore();
  const openSettings = useSettingsStore((s) => s.open);
  const newSession = useChatStore((s) => s.newSession);
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const runningSessions = useChatStore((s) => s.runningSessions);
  const { t } = useI18n();
  const [sessionsOpen, setSessionsOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  const sorted = [...sessions].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    const ta = Number(a.updatedAt || a.createdAt || 0);
    const tb = Number(b.updatedAt || b.createdAt || 0);
    return tb - ta;
  });

  const filtered = searchQuery.trim()
    ? sorted.filter(s => s.title.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    : sorted;

  function handleNewSession() {
    newSession();
    setPage('chat');
  }

  function handleSelectSession(id: string) {
    setActiveSession(id);
    setPage('chat');
  }

  return (
    <div className="ga-left-sidebar">
      <nav className="ga-nav-rail" aria-label="Main navigation">
        <button
          type="button"
          className="ga-nav-btn"
          onClick={handleNewSession}
          aria-label={t('nav.chat')}
        >
          <span className="ga-nav-icon">
            <Codicon name="comment" size="1rem" />
          </span>
          <span className="ga-nav-label">{t('nav.chat')}</span>
        </button>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`ga-nav-btn${activePage === item.key ? ' active' : ''}`}
            onClick={() => setPage(item.key)}
            aria-label={t(item.textKey)}
            aria-current={activePage === item.key ? 'page' : undefined}
          >
            <span className="ga-nav-icon">
              <Codicon name={item.icon} size="1rem" />
            </span>
            <span className="ga-nav-label">{t(item.textKey)}</span>
          </button>
        ))}
      </nav>

      <div className="ga-sidebar-search">
        <Input
          prefix={<IconSearchStroked style={{ fontSize: 14 }} />}
          placeholder={t('search.placeholder')}
          size="small"
          value={searchQuery}
          onChange={setSearchQuery}
        />
      </div>

      {!searchQuery && (
        <SessionSectionHeader
          label={t('section.sessions')}
          count={sessions.length}
          open={sessionsOpen}
          onToggle={setSessionsOpen}
          onAction={handleNewSession}
        />
      )}
      <div className="ga-session-section">
        {(searchQuery || sessionsOpen) && (
          filtered.length === 0 ? (
            <div className="ga-session-empty">
              <p>{searchQuery ? t('search.noResults') : t('conv.emptyList')}</p>
            </div>
          ) : (
            <div className="ga-session-list">
              {filtered.map((s) => (
                <SessionRow
                  key={s.id}
                  session={s}
                  isActive={s.id === activeSessionId}
                  isWorking={runningSessions.has(s.id)}
                  onClick={() => handleSelectSession(s.id)}
                />
              ))}
            </div>
          )
        )}
      </div>

      <div className="ga-sidebar-footer">
        <button
          type="button"
          className="ga-settings-btn"
          onClick={openSettings}
          aria-label={t('foot.settings')}
        >
          <Codicon name="settings-gear" size="1rem" />
        </button>
      </div>
    </div>
  );
}
