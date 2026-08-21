import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

export function ThreadContent({ children }: Props) {
  return (
    <div data-slot="aui_thread-content">
      {children}
    </div>
  );
}
