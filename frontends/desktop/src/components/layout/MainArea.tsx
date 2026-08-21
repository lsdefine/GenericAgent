import { useAppStore } from '../../stores/app';
import { ChatView } from '../chat/ChatView';
import { ServicesPage } from '../services/ServicesPage';
import { TokenPage } from '../token/TokenPage';
import { CollabPage } from '../collab/CollabPage';

export function MainArea() {
  const activePage = useAppStore((s) => s.activePage);

  if (activePage === 'chat') {
    return (
      <div className="ga-main-area ga-main-chat">
        <ChatView />
      </div>
    );
  }

  if (activePage === 'services') {
    return (
      <div className="ga-main-area ga-main-full">
        <ServicesPage />
      </div>
    );
  }

  if (activePage === 'token') {
    return (
      <div className="ga-main-area ga-main-full">
        <TokenPage />
      </div>
    );
  }

  if (activePage === 'collab') {
    return (
      <div className="ga-main-area ga-main-chat">
        <CollabPage />
      </div>
    );
  }

  return <div className="ga-main-area" />;
}
