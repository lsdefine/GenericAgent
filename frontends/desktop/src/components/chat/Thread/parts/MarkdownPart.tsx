import { memo, useMemo, useDeferredValue } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import type { Components } from 'react-markdown';
import 'katex/dist/katex.min.css';
import { CodeBlock } from './CodeBlock';
import { DiffLines } from './DiffLines';
import { SafeMathBlock } from './SafeMath';
import { HugeTextFallback } from './HugeTextFallback';
import { useSmoothReveal } from '../../../../hooks/useSmoothReveal';
import { preprocessMarkdown } from '../../../../lib/markdown-preprocess';

const KATEX_OPTIONS = {
  macros: {
    '\\vline': '\\vert',
    '\\R': '\\mathbb{R}',
    '\\N': '\\mathbb{N}',
    '\\Z': '\\mathbb{Z}',
    '\\Q': '\\mathbb{Q}',
    '\\C': '\\mathbb{C}',
    '\\norm': '\\left\\lVert #1 \\right\\rVert',
    '\\abs': '\\left\\lvert #1 \\right\\rvert',
  },
  strict: 'ignore' as const,
  trust: true,
  errorColor: 'var(--semi-color-text-2)',
};

/** Messages longer than this threshold skip ReactMarkdown entirely. */
const MAX_MARKDOWN_CHARS = 150_000;

interface Props {
  content: string;
  isStreaming?: boolean;
}

function makeComponents(isStreaming: boolean): Components {
  return {
    pre({ children }) {
      return <>{children}</>;
    },
    code({ className, children }) {
      const match = /language-(\w+)/.exec(className || '');
      const code = String(children).replace(/\n$/, '');
      if (match) {
        // Route ```math fences to SafeMathBlock (display math with fallback).
        // ```latex and ```tex go through normal code highlighting.
        if (match[1] === 'math') {
          return <SafeMathBlock expr={code} />;
        }
        if (match[1] === 'diff') {
          return <DiffLines code={code} />;
        }
        return <CodeBlock language={match[1]} code={code} isStreaming={isStreaming} />;
      }
      if (code.includes('\n')) {
        return <CodeBlock code={code} isStreaming={isStreaming} />;
      }
      return <code className={className}>{children}</code>;
    },
    table({ children }) {
      return (
        <div data-slot="md-table-wrap">
          <table>{children}</table>
        </div>
      );
    },
  };
}

export const MarkdownPart = memo(function MarkdownPart({ content, isStreaming = false }: Props) {
  const components = useMemo(() => makeComponents(isStreaming), [isStreaming]);
  const revealed = useSmoothReveal(content, isStreaming);

  // Wrap in useDeferredValue so streaming markdown parsing doesn't block UI updates.
  const deferredText = useDeferredValue(revealed);

  // For extremely long messages, skip markdown rendering entirely.
  if (deferredText.length > MAX_MARKDOWN_CHARS) {
    return (
      <div data-slot="aui_markdown-part">
        <HugeTextFallback text={deferredText} />
      </div>
    );
  }

  return (
    <div data-slot="aui_markdown-part">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, KATEX_OPTIONS]]}
        components={components}
      >
        {preprocessMarkdown(deferredText)}
      </ReactMarkdown>
    </div>
  );
});
