import { memo } from 'react';
import { renderMathCached } from '../../../../lib/katex-memo';

interface Props {
  expr: string;
}

/**
 * SafeMathBlock renders a KaTeX display math expression with LRU-cached
 * 3-level fallback (strict → lenient → error span).
 *
 * Uses the module-level memo cache so repeated renders during streaming
 * do not re-invoke katex.renderToString.
 */
export const SafeMathBlock = memo(function SafeMathBlock({ expr }: Props) {
  const html = renderMathCached(expr, true);
  return <div data-slot="math-display" dangerouslySetInnerHTML={{ __html: html }} />;
});
