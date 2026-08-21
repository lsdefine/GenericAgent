interface GaLegacy {
  applyAppearance: (app: string, plain: boolean, opts: { persist: boolean }) => void;
  applyI18n: () => void;
  syncHljsTheme: () => void;
  selectModel: (no: number, name: string) => void;
  updateModelChip: () => void;
  renderSessionList: () => void;
  refreshStatusLabel: () => void;
}

function legacy(): GaLegacy {
  return (window as unknown as { gaLegacy: GaLegacy }).gaLegacy;
}

export function applyAppearance(app: string, plain: boolean) {
  legacy().applyAppearance(app, plain, { persist: false });
}

export function applyI18n() {
  legacy().applyI18n();
}

export function syncHljsTheme() {
  legacy().syncHljsTheme();
}

export function selectModel(no: number, name: string) {
  legacy().selectModel(no, name);
}

export function updateModelChip() {
  legacy().updateModelChip();
}

export function refreshAfterLangChange() {
  legacy().applyI18n();
  legacy().renderSessionList();
  legacy().refreshStatusLabel();
  legacy().updateModelChip();
}
