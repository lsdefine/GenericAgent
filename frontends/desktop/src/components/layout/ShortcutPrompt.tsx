import { useEffect, useRef } from 'react';
import { Modal } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';

export function ShortcutPrompt() {
  const asked = useRef(false);
  const { t } = useI18n();

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;

    // macOS apps are discoverable via Spotlight/Launchpad — no shortcut prompt needed.
    if (document.documentElement.dataset.platform === 'macos') return;

    const invoke = (window as any).__TAURI__?.core?.invoke;
    if (!invoke) return;

    (async () => {
      try {
        const should = await invoke('shortcut_should_ask');
        if (!should) return;
        Modal.confirm({
          title: t('common.confirm'),
          content: t('shortcut.askConfirm'),
          onOk: () => invoke('shortcut_decide', { create: true }),
          onCancel: () => invoke('shortcut_decide', { create: false }),
        });
      } catch { /* not in tauri bundle — ignore */ }
    })();
  }, [t]);

  return null;
}
