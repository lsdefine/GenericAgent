import { useEffect, useState, useCallback } from 'react';
import { Modal } from '@douyinfe/semi-ui';
import { useSettingsStore } from '../../stores/settings';
import { useI18n } from '../../i18n';
import './settings.css';
import { AppearanceSection } from './AppearanceSection';
import { LanguageSection } from './LanguageSection';
import { ModelSection } from './ModelSection';
import { DataSection } from './DataSection';
import { FeatureSection } from './FeatureSection';
import { AddModelView } from './AddModelView';

type View = 'main' | 'addModel';

export function SettingsModal() {
  const { visible, open, close, loadFromBridge } = useSettingsStore();
  const { t } = useI18n();

  const [view, setView] = useState<View>('main');
  const [editingId, setEditingId] = useState<number | null>(null);

  useEffect(() => {
    const handler = () => {
      loadFromBridge();
      open();
    };
    const closeHandler = () => close();
    window.addEventListener('ga:open-settings', handler);
    window.addEventListener('ga:close-settings', closeHandler);
    return () => {
      window.removeEventListener('ga:open-settings', handler);
      window.removeEventListener('ga:close-settings', closeHandler);
    };
  }, [open, close, loadFromBridge]);

  useEffect(() => {
    if (!visible) {
      setView('main');
      setEditingId(null);
    }
  }, [visible]);

  const handleAddModel = useCallback(() => {
    setEditingId(null);
    setView('addModel');
  }, []);

  const handleEditModel = useCallback((id: number) => {
    setEditingId(id);
    setView('addModel');
  }, []);

  const handleModelDone = useCallback(() => {
    setView('main');
    setEditingId(null);
  }, []);

  const title = view === 'main'
    ? t('modal.settings')
    : (editingId != null ? t('modal.editModel') : t('modal.addModel'));

  return (
    <Modal
      visible={visible}
      onCancel={close}
      title={title}
      footer={null}
      width={870}
      centered
      closeOnEsc
      className="ga-settings-dialog"
    >
      {view === 'main' ? (
        <>
          <AppearanceSection />
          <LanguageSection />
          <ModelSection onAdd={handleAddModel} onEdit={handleEditModel} />
          <DataSection />
          <FeatureSection />
        </>
      ) : (
        <AddModelView editingId={editingId} onDone={handleModelDone} />
      )}
    </Modal>
  );
}
