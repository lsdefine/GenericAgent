import type { ComponentProps } from 'react';
import './log.css';

export function LogView({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={`ga-log-view ${className ?? ''}`}
      data-selectable-text="true"
      {...props}
    />
  );
}
