import { useRef, useMemo } from 'react';
import { useI18n } from '../../../i18n';
import { useChatStore } from '../../../stores/chat';

const NEW_COUNT = 7;
const FOLLOWUP_COUNT = 5;

function pickRandom(max: number): number {
  return Math.floor(Math.random() * max);
}

export function usePlaceholder(): { text: string } {
  const { t } = useI18n();
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const hasMessages = useChatStore((s) => s.messages.length > 0);

  const rolledRef = useRef<{ sessionId: string | null; index: number; wasNew: boolean }>({
    sessionId: null,
    index: pickRandom(NEW_COUNT),
    wasNew: true,
  });

  const text = useMemo(() => {
    const prev = rolledRef.current;

    if (prev.sessionId !== activeSessionId) {
      const isNew = !hasMessages;
      const count = isNew ? NEW_COUNT : FOLLOWUP_COUNT;
      const index = pickRandom(count);
      rolledRef.current = { sessionId: activeSessionId, index, wasNew: isNew };
      const pool = isNew ? 'new' : 'followUp';
      return t(`composer.placeholder.${pool}.${index}`);
    }

    const pool = prev.wasNew ? 'new' : 'followUp';
    return t(`composer.placeholder.${pool}.${prev.index}`);
  }, [activeSessionId, hasMessages, t]);

  return { text };
}
