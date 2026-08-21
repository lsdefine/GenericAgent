import { useNotificationStore } from '../stores/notifications';

function notify(message: string, kind: 'error' | 'warning' | 'info' | 'success') {
  useNotificationStore.getState().notify({ kind, message });
}

export function showToast(content: string) {
  notify(content, 'info');
}

export function showError(content: string) {
  notify(content, 'error');
}

export function showSuccess(content: string) {
  notify(content, 'success');
}

export function showSystem(content: string) {
  notify(content, 'info');
}
