export class ChatPage {
  get navigation() { return $('nav[aria-label="Main navigation"]'); }
  get editor() { return $('[role="textbox"][contenteditable="true"]'); }
  get sendButton() { return $('button[aria-label="Send message"]'); }
  get assistants() { return $$('[data-role="assistant"]'); }

  async waitUntilReady(): Promise<void> {
    await this.navigation.waitForDisplayed({ timeout: 20_000 });
  }

  async switchToMainAndWait(): Promise<void> {
    // Windows WebDriver can initially attach to the visible setup window even
    // after bootstrap has navigated and shown the main window.
    await browser.tauri.switchWindow('main');
    await this.waitUntilReady();
  }

  async waitForBridgeReady(): Promise<void> {
    await browser.waitUntil(async () => !(await $('.ga-chat-offline').isExisting()), {
      timeout: 30_000,
      interval: 200,
      timeoutMsg: 'Bridge did not reach ready state in the UI',
    });
  }

  async startNewChat(): Promise<void> {
    let button: ReturnType<typeof $> | undefined;
    await browser.waitUntil(async () => {
      try {
        const candidate = $('button[aria-label="新建会话"], button[aria-label="New Session"]');
        if (!await candidate.isDisplayed() || !await candidate.isEnabled()) return false;
        button = candidate;
        return true;
      } catch {
        // Tauri may replace the renderer while bootstrap reopens the main UI.
        return false;
      }
    }, {
      timeout: 20_000,
      interval: 100,
      timeoutMsg: 'New chat action did not become available',
    });
    await button!.click();
    await this.editor.waitForDisplayed({ timeout: 10_000 });
  }

  async send(text: string): Promise<void> {
    const editor = await this.editor;
    await editor.click();
    await browser.execute((element, value) => {
      const target = element as unknown as HTMLElement;
      target.textContent = value;
      target.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        inputType: 'insertText',
        data: value,
      }));
    }, editor, text);
    await this.sendButton.waitForEnabled({ timeout: 5_000 });
    await this.sendButton.click();
  }

  async waitForAssistantText(text: string, timeout = 30_000): Promise<void> {
    await browser.waitUntil(async () => {
      const items = await this.assistants as unknown as WebdriverIO.Element[];
      if (!items.length) return false;
      return (await items[items.length - 1].getText()).includes(text);
    }, { timeout, interval: 200, timeoutMsg: `Assistant did not render: ${text}` });
  }
}
