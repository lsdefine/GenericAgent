import { useEffect, useState } from 'react';
import { Modal, TextArea, Button, Spin } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import { useServicesStore } from '../../stores/services';
import { showError, showSuccess } from '../../utils/toast';
import '../settings/settings.css';

interface Props {
  visible: boolean;
  onClose: () => void;
}

export function MykeyConfigModal({ visible, onClose }: Props) {
  const { t } = useI18n();
  const fetchMykey = useServicesStore((s) => s.fetchMykey);
  const saveMykey = useServicesStore((s) => s.saveMykey);
  const mykeyContent = useServicesStore((s) => s.mykeyContent);
  const mykeyLoading = useServicesStore((s) => s.mykeyLoading);

  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      fetchMykey();
    }
  }, [visible, fetchMykey]);

  useEffect(() => {
    setDraft(mykeyContent);
  }, [mykeyContent]);

  const handleSave = async () => {
    setSaving(true);
    const ok = await saveMykey(draft);
    setSaving(false);
    if (ok) {
      showSuccess(t('sys.configSaved'));
      onClose();
    } else {
      showError(t('err.mykeyExport'));
    }
  };

  return (
    <Modal
      title={t('modal.mykeyConfig')}
      visible={visible}
      onCancel={onClose}
      width={870}
      centered
      closeOnEsc
      className="ga-settings-dialog"
      footer={
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', padding: '8px 0' }}>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="primary" loading={saving} onClick={handleSave}>
            {t('common.save')}
          </Button>
        </div>
      }
    >
      {mykeyLoading ? (
        <div className="ga-services-loading">
          <Spin />
        </div>
      ) : (
        <TextArea
          value={draft}
          onChange={(v) => setDraft(v)}
          autosize={{ minRows: 16, maxRows: 30 }}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
        />
      )}
    </Modal>
  );
}
