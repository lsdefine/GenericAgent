import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { preprocessMarkdown } from '../../../../lib/markdown-preprocess';

const KATEX_OPTIONS = {
  strict: 'ignore' as const,
  trust: true,
};

interface Props {
  content: string;
}

export const SummaryPart = memo(function SummaryPart({ content }: Props) {
  return (
    <div data-slot="summary-block">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, KATEX_OPTIONS]]}
      >
        {preprocessMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
});
