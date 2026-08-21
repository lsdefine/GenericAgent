// @vitest-environment happy-dom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { UserMessage } from '../components/chat/Thread/UserMessage';

const PLAN_PROMPT = 'Enter Plan mode: read memory/plan_sop.md, follow Explore → Plan → Execute → Verify flow for the task I describe next.';

describe('UserMessage', () => {
  const originalResizeObserver = globalThis.ResizeObserver;

  beforeEach(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    globalThis.ResizeObserver = originalResizeObserver;
  });

  it('returns null when there is no content, image, or file', () => {
    const { container } = render(<UserMessage content="" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders file chips for files-only messages', () => {
    const { container } = render(
      <UserMessage
        content=""
        files={[
          { name: 'report.csv', path: '/tmp/report.csv', size: 1536 },
          { name: 'README.md', path: '/tmp/README.md', size: 0 },
        ]}
      />,
    );

    expect(screen.getByText('report.csv')).not.toBeNull();
    expect(screen.getByText('1.5 KB')).not.toBeNull();
    expect(screen.getByText('README.md')).not.toBeNull();
    expect(container.querySelectorAll('[data-slot="user-file-chip"]').length).toBe(2);
    expect(container.textContent?.includes('¶')).toBe(true);
  });

  it('renders remote image URLs through the bridge raw endpoint', () => {
    render(
      <UserMessage
        content="see this"
        images={[{ name: 'diagram.png', path: '/tmp/uploads/diagram.png' }]}
      />,
    );

    const image = screen.getByAltText('diagram.png') as HTMLImageElement;
    expect(image.getAttribute('src')).toBe(
      'http://127.0.0.1:14168/upload/raw?path=%2Ftmp%2Fuploads%2Fdiagram.png',
    );
  });

  it('preserves data URLs for pasted images', () => {
    render(
      <UserMessage
        content="inline image"
        images={[{ name: 'clipboard.png', path: 'data:image/png;base64,AAAA' }]}
      />,
    );

    const image = screen.getByAltText('clipboard.png') as HTMLImageElement;
    expect(image.getAttribute('src')).toBe('data:image/png;base64,AAAA');
  });

  it('renders skill-chip transcript shorthand plus remaining text', () => {
    render(
      <UserMessage
        content={`${PLAN_PROMPT} compare attachment rendering next`}
        msgId="42"
      />,
    );

    expect(screen.getByText('/plan')).not.toBeNull();
    expect(screen.getByText(/compare attachment rendering next/)).not.toBeNull();
    const root = document.querySelector('[data-slot="aui_user-message-root"]') as HTMLDivElement;
    expect(root.getAttribute('id')).toBe('msg-42');
    expect(root.getAttribute('data-msg-id')).toBe('42');
  });

  it('renders images, files, and bubble content together', () => {
    const { container } = render(
      <UserMessage
        content="attached both"
        images={[{ name: 'snap.png', path: 'data:image/png;base64,BBBB' }]}
        files={[{ name: 'notes.txt', path: '/tmp/notes.txt', size: 12 }]}
      />,
    );

    expect(container.querySelector('[data-slot="user-images"]')).not.toBeNull();
    expect(container.querySelector('[data-slot="user-files"]')).not.toBeNull();
    expect(screen.getByText('attached both')).not.toBeNull();
  });
});
