// @vitest-environment happy-dom
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AttachmentStrip, type AttachmentFile } from '../components/chat/Composer/AttachmentStrip';

function file(overrides: Partial<AttachmentFile> = {}): AttachmentFile {
  return {
    id: 'file-1',
    name: 'notes.txt',
    size: 1536,
    type: 'file',
    status: 'ready',
    ...overrides,
  };
}

describe('AttachmentStrip', () => {
  it('returns no visible content when there are no attachments', () => {
    const { container } = render(<AttachmentStrip files={[]} onRemove={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders an uploading file with spinner and no remove button', () => {
    const { container } = render(
      <AttachmentStrip
        files={[file({ status: 'uploading' })]}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByText('notes.txt')).not.toBeNull();
    expect(screen.getByText('1.5 KB')).not.toBeNull();
    expect(container.querySelector('[data-slot="attachment-spinner"]')).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
  });

  it('renders an error file with retry badge, error text, and removable control', () => {
    const onRemove = vi.fn();
    const onRetry = vi.fn();
    const { container } = render(
      <AttachmentStrip
        files={[file({ status: 'error', errorMsg: 'upload failed' })]}
        onRemove={onRemove}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText('notes.txt')).not.toBeNull();
    expect(screen.getByText('upload failed')).not.toBeNull();

    const retry = screen.getByTitle('upload failed');
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledWith('file-1');

    const remove = screen.getByRole('button', { name: 'Remove' });
    fireEvent.click(remove);
    expect(onRemove).toHaveBeenCalledWith('file-1');

    expect(container.querySelector('[data-slot="attachment-file-size"]')).toBeNull();
  });

  it('renders a URL attachment using the hostname as label', () => {
    render(
      <AttachmentStrip
        files={[file({ id: 'url-1', type: 'url', name: 'fallback', url: 'https://docs.nousresearch.com/path?q=1' })]}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByText('docs.nousresearch.com')).not.toBeNull();
  });

  it('renders an image thumbnail and remove control when ready', () => {
    render(
      <AttachmentStrip
        files={[file({ id: 'img-1', type: 'image', status: 'ready', preview: 'data:image/png;base64,AAAA', name: 'diagram.png' })]}
        onRemove={vi.fn()}
      />,
    );

    const image = screen.getByAltText('diagram.png') as HTMLImageElement;
    expect(image.getAttribute('src')).toBe('data:image/png;base64,AAAA');
    expect(screen.getByRole('button', { name: 'Remove' })).not.toBeNull();
  });
});
