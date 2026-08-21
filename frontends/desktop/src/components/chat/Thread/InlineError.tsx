import { memo } from 'react';
import { useI18n } from '../../../i18n';
import { summarizeError } from '../../../lib/error-summary';

interface Props {
  error: string;
  msgId: string;
}

export const InlineError = memo(function InlineError({ error, msgId }: Props) {
  const { t } = useI18n();
  const display = summarizeError(error, t);

  return (
    <div className="ga-inline-error" role="alert" id={`msg-${msgId}`}>
      <span className="ga-inline-error-text">{display}</span>
    </div>
  );
});
