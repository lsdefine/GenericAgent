export class UsagePage {
  get totalTokens() { return $('[data-testid="token-stat-value-tok.total"]'); }
  get cacheRate() { return $('[data-testid="token-stat-value-tok.cost"]'); }

  async open(): Promise<void> {
    const button = await $('nav[aria-label="Main navigation"] button[aria-label="用量"], nav[aria-label="Main navigation"] button[aria-label="Usage"]');
    await button.waitForExist({ timeout: 10_000 });
    await button.click();
    await this.totalTokens.waitForDisplayed({ timeout: 10_000 });
  }

  async waitForTotal(expected: string, timeout = 20_000): Promise<void> {
    await browser.waitUntil(async () => (await this.totalTokens.getText()) === expected, {
      timeout,
      interval: 250,
      timeoutMsg: `Expected total token count ${expected}`,
    });
  }
}
