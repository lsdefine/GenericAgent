export class RecoveryPage {
  get offlineBanner() { return $('.ga-chat-offline'); }
  get restartButton() { return $('[data-testid="bridge-restart"]'); }

  async waitForOffline(timeout = 20_000): Promise<void> {
    await this.offlineBanner.waitForDisplayed({ timeout });
  }

  async recoverFromServices(): Promise<void> {
    const services = await $('nav[aria-label="Main navigation"] button[aria-label="后台服务"], nav[aria-label="Main navigation"] button[aria-label="Services"]');
    await services.click();
    await this.restartButton.waitForDisplayed({ timeout: 20_000 });
    await this.restartButton.click();
  }

  async retryFromServices(): Promise<void> {
    await browser.waitUntil(async () => {
      try {
        const buttons = await $$('[data-testid="bridge-restart"]') as unknown as WebdriverIO.Element[];
        for (const button of buttons) {
          if (await button.isDisplayed() && await button.isEnabled()) return true;
        }
      } catch { /* the status poll may replace the button between queries */ }
      return false;
    }, { timeout: 20_000, interval: 100, timeoutMsg: 'Restart action did not become available' });
    const buttons = await $$('[data-testid="bridge-restart"]') as unknown as WebdriverIO.Element[];
    for (const button of buttons) {
      if (await button.isDisplayed() && await button.isEnabled()) {
        await button.click();
        return;
      }
    }
    throw new Error('Visible restart action disappeared before it could be clicked');
  }
}
