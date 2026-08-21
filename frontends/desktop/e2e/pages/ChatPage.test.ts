import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from './ChatPage';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ChatPage native window selection', () => {
  it('switches to the main Tauri window before waiting for its renderer', async () => {
    const order: string[] = [];
    vi.stubGlobal('browser', {
      tauri: {
        switchWindow: vi.fn(async (label: string) => {
          order.push(`switch:${label}`);
        }),
      },
    });

    class TestChatPage extends ChatPage {
      override async waitUntilReady(): Promise<void> {
        order.push('ready');
      }
    }

    await new TestChatPage().switchToMainAndWait();

    expect(order).toEqual(['switch:main', 'ready']);
  });

  it('retries a semantic new-chat lookup while the Tauri renderer is being replaced', async () => {
    const click = vi.fn(async () => undefined);
    const waitForDisplayed = vi.fn(async () => undefined);
    const lookup = vi.fn()
      .mockImplementationOnce(() => {
        throw new Error('transient WebDriver javascript exception');
      })
      .mockImplementation((selector: string) => {
        if (selector.includes('aria-label="New Session"')) {
          return {
            isDisplayed: vi.fn(async () => true),
            isEnabled: vi.fn(async () => true),
            click,
          };
        }
        if (selector.includes('role="textbox"')) return { waitForDisplayed };
        throw new Error(`Unexpected selector: ${selector}`);
      });
    vi.stubGlobal('$', lookup);
    vi.stubGlobal('browser', {
      waitUntil: vi.fn(async (predicate: () => Promise<boolean>) => {
        expect(await predicate()).toBe(false);
        expect(await predicate()).toBe(true);
      }),
    });

    await new ChatPage().startNewChat();

    expect(click).toHaveBeenCalledOnce();
    expect(waitForDisplayed).toHaveBeenCalledOnce();
  });
});
