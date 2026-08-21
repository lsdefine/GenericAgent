const ZH = (navigator.language || '').toLowerCase().startsWith('zh');

const messages = {
  starting: ZH ? '正在启动 GenericAgent' : 'Starting GenericAgent',
  resuming: ZH ? '正在恢复 GenericAgent' : 'Resuming GenericAgent',
  preparing: ZH ? '首次启动，正在准备本地运行环境' : 'First launch: preparing the local runtime',
  stage_validate: ZH ? '检查本地文件' : 'Checking local files',
  stage_python: ZH ? '准备 Python 环境' : 'Preparing Python environment',
  stage_dependencies: ZH ? '安装运行组件' : 'Installing runtime components',
  stage_service: ZH ? '启动后台服务' : 'Starting background service',
  stage_ui: ZH ? '打开主界面' : 'Opening the main window',
  ready: ZH ? '就绪' : 'Ready',
  readyDetail: ZH ? '正在进入主界面…' : 'Entering main interface…',
  failed: ZH ? '启动失败' : 'Startup failed',
  retry: ZH ? '重试' : 'Retry',
  configure: ZH ? '手动配置' : 'Configure',
  pythonPath: ZH ? 'Python 解释器路径' : 'Python interpreter path',
  projectDir: ZH ? 'GenericAgent 位置' : 'GenericAgent location',
  projectDirHint: ZH ? '你的 GA 仓库路径，已有记忆和自定义代码都会保留' : 'Path to your GA repository. Memory and custom code will be preserved.',
  start: ZH ? '启动' : 'Start',
  startingBridge: ZH ? '正在启动…' : 'Starting…',
  connected: ZH ? '已连接' : 'Connected',
  settings: ZH ? '配置' : 'Settings',
  logTitle: ZH ? '日志' : 'Log',
} as const;

export function t(key: keyof typeof messages): string {
  return messages[key];
}

/** Safe lookup: returns the message if the key exists, otherwise the fallback. */
export function tOr(key: string, fallback: string): string {
  return (messages as Record<string, string>)[key] ?? fallback;
}
