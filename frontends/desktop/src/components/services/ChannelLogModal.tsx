import { useEffect, useState, useCallback, useRef } from 'react';
import { Modal, Spin } from '@douyinfe/semi-ui';
import { useI18n } from '../../i18n';
import { useServicesStore } from '../../stores/services';
import { LogTail } from '../log';

interface Props {
  serviceId: string | null;
  onClose: () => void;
}

const REFRESH_INTERVAL = 3000;

export function ChannelLogModal({ serviceId, onClose }: Props) {
  const { t } = useI18n();
  const fetchLogs = useServicesStore((s) => s.fetchLogs);
  const [lines, setLines] = useState<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadLogs = useCallback(async () => {
    if (!serviceId) return;
    const result = await fetchLogs(serviceId);
    setLines(result);
  }, [serviceId, fetchLogs]);

  useEffect(() => {
    if (serviceId) {
      setLines(null);
      loadLogs();
      timerRef.current = setInterval(loadLogs, REFRESH_INTERVAL);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [serviceId, loadLogs]);

  return (
    <Modal
      title={t('modal.channelLogs')}
      visible={serviceId !== null}
      onCancel={onClose}
      footer={null}
      width={870}
      centered
      closeOnEsc
      className="ga-log-dialog"
    >
      {lines === null ? (
        <div className="ga-services-loading" style={{ padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <LogTail lines={lines} emptyLabel={t('ch.logEmpty')} className="ga-log-modal-body" />
      )}
    </Modal>
  );
}
