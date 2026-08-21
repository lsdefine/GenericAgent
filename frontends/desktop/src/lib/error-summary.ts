import type { useI18n } from '../i18n';

interface ErrorRule {
  pattern: RegExp;
  key: string;
}

const ERROR_RULES: ErrorRule[] = [
  { pattern: /invalid.?api.?key|api.?key.?invalid|Incorrect API key/i, key: 'err.apiKeyInvalid' },
  { pattern: /model.*not found|does not exist|model_not_found/i, key: 'err.modelNotFound' },
  { pattern: /rate.?limit|429|Too Many Requests/i, key: 'err.rateLimit' },
  { pattern: /quota|insufficient.?funds|balance|billing/i, key: 'err.quotaExceeded' },
  { pattern: /timed?\s*out|TimeoutError/i, key: 'err.timeout' },
  { pattern: /Connection\s*refused|ConnectionRefusedError/i, key: 'err.connRefused' },
  { pattern: /errno 48|address already in use/i, key: 'err.portBusy' },
  { pattern: /Traceback|Exception.*thread|exit code \d+/i, key: 'err.processCrash' },
];

type TFn = ReturnType<typeof useI18n>['t'];

export function summarizeError(raw: string, t: TFn): string {
  if (!raw) return '';
  for (const rule of ERROR_RULES) {
    if (rule.pattern.test(raw)) return t(rule.key);
  }
  return raw.length <= 80 ? raw : raw.slice(0, 77) + '…';
}
