import { useState, useCallback } from 'react';
import { Button, Toast, Tooltip } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import * as bridge from '../../services/bridge';
import { useChatStore } from '../../stores/chat';
import { useSettingsStore } from '../../stores/settings';
import { GaSourceBlock } from './GaSourceBlock';
import { BRIDGE_BASE } from '../../services/constants';

const isTauri = !!(window as any).__TAURI__;

interface OpRowProps {
  label: string;
  tip: string;
  btnText: string;
  onClick: () => void;
  disabled?: boolean;
}

function OpRow({ label, tip, btnText, onClick, disabled }: OpRowProps) {
  return (
    <div className="ga-data-row">
      <div className="ga-data-row-info">
        <Tooltip content={tip}>
          <span className="ga-data-row-label">{label}</span>
        </Tooltip>
      </div>
      <Button size="small" type="tertiary" onClick={onClick} disabled={disabled}>
        {btnText}
      </Button>
    </div>
  );
}

export function DataSection() {
  const { t } = useI18n();
  const [importing, setImporting] = useState(false);

  const handleImportKey = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.py,text/plain';
    input.onchange = async () => {
      try {
        const file = input.files?.[0];
        if (!file) return;
        const text = await file.text();
        await bridge.saveMykeyContent(text);
        await useSettingsStore.getState().loadFromBridge();
        Toast.success({ content: t('data.importKeySuccess') });
      } catch (e) {
        console.error('[DataSection] importKey failed:', e);
        Toast.error({ content: t('data.importKeyError') });
      }
    };
    input.click();
  }, [t]);

  const handleExportKey = useCallback(async () => {
    try {
      const content = await bridge.getMykeyContent();
      if (isTauri) {
        try {
          const path = await bridge.tauriInvoke('export_mykey', { content });
          if (path) Toast.success({ content: t('data.exportKeySuccess') });
        } catch {
          downloadAsFile(content, 'mykey.py');
          Toast.success({ content: t('data.exportKeySuccess') });
        }
      } else {
        downloadAsFile(content, 'mykey.py');
        Toast.success({ content: t('data.exportKeySuccess') });
      }
    } catch (e) {
      console.error('[DataSection] exportKey failed:', e);
      Toast.error({ content: t('data.exportKeyError') });
    }
  }, [t]);

  const handleImportData = useCallback(async () => {
    try {
      const picked = await bridge.tauriInvoke('pick_directory', {}) as string | null;
      if (!picked) return;

      setImporting(true);
      try {
        const res = await fetch(`${BRIDGE_BASE}/memory/import`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sourceDir: picked }),
        });
        const data = await res.json();
        if (!res.ok) {
          Toast.error({ content: data?.error || t('data.importDataError') });
          return;
        }
        const copied = (data.memoryCopied || 0) + (data.responsesCopied || 0) + (data.sessionsAdded || 0);
        const skipped = data.responsesSkipped || 0;
        Toast.success({ content: t('data.importDataSuccess', { copied, skipped }) });
        useChatStore.getState().loadSessions();
      } finally {
        setImporting(false);
      }
    } catch (e: any) {
      setImporting(false);
      console.error('[DataSection] importData failed:', e);
      if (e?.message?.includes('Tauri')) return;
      Toast.error({ content: t('data.importDataError') });
    }
  }, [t]);

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">{t('data.title')}</div>
      <OpRow
        label={t('data.importKey')}
        tip={t('data.importKeyTip')}
        btnText={t('data.importKeyBtn')}
        onClick={handleImportKey}
      />
      <OpRow
        label={t('data.exportKey')}
        tip={t('data.exportKeyTip')}
        btnText={t('data.exportKeyBtn')}
        onClick={handleExportKey}
      />
      {isTauri && (
        <>
          <OpRow
            label={t('data.importData')}
            tip={t('data.importDataTip')}
            btnText={t('data.importDataBtn')}
            onClick={handleImportData}
            disabled={importing}
          />
          <div className="ga-data-divider" />
          <GaSourceBlock />
        </>
      )}
    </div>
  );
}

function downloadAsFile(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
