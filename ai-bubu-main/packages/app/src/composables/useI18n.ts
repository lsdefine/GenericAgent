import { ref, computed } from 'vue'

export type Lang = 'zh' | 'en'

const LANG_KEY = 'aibubu-lang'

function detectSystemLang(): Lang {
  try {
    const nav = navigator.language || ''
    if (nav.startsWith('zh')) return 'zh'
  } catch {
    /* noop */
  }
  return 'en'
}

function loadLang(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    /* noop */
  }
  return detectSystemLang()
}

export const currentLang = ref<Lang>(loadLang())

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === LANG_KEY && (e.newValue === 'zh' || e.newValue === 'en')) {
      currentLang.value = e.newValue
    }
  })
}

const messages: Record<Lang, Record<string, string>> = {
  zh: {
    brand: 'AI 步步',
    today: '今日',
    leaderboard: '排行',
    skins: '角色',
    settings: '设置',

    todayOverview: '今日概览',
    todaySteps: '今日步数',
    currentActivity: '当前活跃度',
    todayPeak: '今日峰值',
    activeDuration: '活跃时长',
    history: '历史记录',
    historyDays: '天',
    historyEmpty: '暂无历史数据，明天再来看看',

    stateIdle: '空闲',
    stateWalk: '散步',
    stateRun: '跑步',
    stateSprint: '飞跑',

    weekSun: '周日',
    weekMon: '周一',
    weekTue: '周二',
    weekWed: '周三',
    weekThu: '周四',
    weekFri: '周五',
    weekSat: '周六',

    lbTitle: '排行榜',
    lbPeople: '人',
    lbEmpty: '开启局域网发现，看看谁在线',
    lbEmptySearching: '正在寻找附近的同事…',
    lbSelf: '我',

    skinsTitle: '角色',
    skinsCurrent: '当前角色',
    skinsChange: '更换角色',
    skinsActive: '当前',
    skinsRemoveConfirm: '确定要移除这个角色吗？移除后不可恢复。',
    skinsRemoving: '移除中...',
    skinsRemoveOk: '确定移除',
    skinsCancel: '取消',
    skinsImport: '导入角色',
    skinsGuideFormat: '格式说明',
    skinsFormat: '格式',
    skinsFormatVal: 'Sprite Sheet（PNG）',
    skinsRequired: '必需文件',
    skinsRequiredVal: 'skin.json + 精灵图 + pet.png',
    skinsPetPng: 'pet.png',
    skinsPetPngVal: '角色头像（支持 pet.gif）',
    skinsStates: '必需状态',
    skinsStatesVal: 'idle, walk, run, sprint',
    skinsSkinJson: 'skin.json',
    skinsSkinJsonVal: 'name, author, format, size, animations',
    skinsOptional: '可选字段',
    skinsOptionalVal: 'source（来源URL）、license（授权协议）',
    skinsDownloadExample: '下载示例（含制作说明）',
    skinsImportFolder: '导入文件夹',
    skinsImportZip: '导入 ZIP',
    skinsSelectFolder: '选择角色文件夹',
    skinsSelectZip: '选择角色压缩包',
    skinsZipFilter: '压缩包',
    skinsRemoveBtn: '移除角色',

    settingsTitle: '设置',
    settingsProfile: '个人信息',
    settingsNickname: '昵称',
    settingsNicknamePlaceholder: '输入昵称',
    settingsGeneral: '通用',
    settingsTheme: '外观模式',
    settingsThemeHint: '控制面板的配色方案',
    settingsThemeLight: '浅色',
    settingsThemeDark: '深色',
    settingsThemeSystem: '系统',
    settingsShowOverFullscreen: '全屏时显示',
    settingsShowOverFullscreenHint: '在其他应用全屏时仍然显示桌宠',
    settingsAutoStart: '开机自启动',
    settingsAutoStartHint: '登录系统时自动运行 AI 步步',
    updateTitle: '应用更新',
    updateCheck: '检查更新',
    updateUpToDate: '当前已是最新版本',
    updateChecking: '正在检查...',
    updateNewVersion: '发现新版本',
    updateDownloading: '正在下载更新...',
    updateReadyRestart: '下载完成，重启即可更新',
    updateCheckBtn: '检查更新',
    updateDownloadBtn: '下载更新',
    updateRestartBtn: '重启更新',

    settingsLan: '局域网发现',
    settingsLanHint: '允许同一网络下的同事发现你',

    about: '关于',
    aboutDesc: 'AI 时代的编码计步器',
    aboutVersion: '版本',
    aboutDeveloper: '开发者',
    aboutWebsite: '官网',
    aboutGitHub: 'GitHub',
    aboutGitHubHint: '觉得不错？给个 Star 支持一下',
    aboutPrivacy: '隐私政策',
    aboutPrivacyHint: '所有数据仅存储在本地，不会上传到任何服务器',
    aboutPrivacyPolicy: '查看隐私政策',
    aboutLicense: '开源协议',
    aboutFeedback: '反馈建议',
    aboutFeedbackHint: '遇到问题或有好点子？欢迎提 Issue',

    connected: '人在线',
    disconnected: '未连接',
    disconnectedHint: '前往设置开启局域网发现',

    trayShow: '显示桌宠',
    trayHide: '隐藏桌宠',
    trayLeaderboard: '排行榜',
    trayQuit: '退出',

    steps: '步',
    anonymous: '匿名',
    skinCannotRemove: '内置角色不能移除',
    skinRemoveFail: '移除失败',
    skinImportFail: '导入失败',
    dragHint: '按住拖拽',

    statsTitle: '数据洞察',
    statsWeekTrend: '近 7 天趋势',
    statsMonthTrend: '近 30 天趋势',
    statsHeatmap: '活跃时段',
    statsHeatmapHint: '24 小时活跃度分布',
    statsProviders: '工具使用',
    statsProvidersHint: '各 AI 工具活跃时长占比',
    statsStreak: '连续活跃',
    statsStreakDays: '天',
    statsNoData: '暂无数据',
    statsSteps: '步',
    historyDetailHourly: '小时分布',
    historyDetailProviders: '工具使用',
    historyNoDetail: '无详细数据',

    moodNormal: '',
    moodSleepy: '💤',
    moodExcited: '🔥',
    moodHappy: '😊',
    interactHint: '单击互动 · 右键菜单',
  },
  en: {
    brand: 'AIbubu',
    today: 'Today',
    leaderboard: 'Rank',
    skins: 'Skins',
    settings: 'Settings',

    todayOverview: "Today's Overview",
    todaySteps: "Today's Steps",
    currentActivity: 'Current Activity',
    todayPeak: "Today's Peak",
    activeDuration: 'Active Time',
    history: 'History',
    historyDays: 'd',
    historyEmpty: 'No history yet, check back tomorrow',

    stateIdle: 'Idle',
    stateWalk: 'Walking',
    stateRun: 'Running',
    stateSprint: 'Sprinting',

    weekSun: 'Sun',
    weekMon: 'Mon',
    weekTue: 'Tue',
    weekWed: 'Wed',
    weekThu: 'Thu',
    weekFri: 'Fri',
    weekSat: 'Sat',

    lbTitle: 'Leaderboard',
    lbPeople: '',
    lbEmpty: "Enable LAN discovery to see who's online",
    lbEmptySearching: 'Searching for nearby teammates…',
    lbSelf: 'Me',

    skinsTitle: 'Skins',
    skinsCurrent: 'Current Skin',
    skinsChange: 'Change Skin',
    skinsActive: 'Active',
    skinsRemoveConfirm: 'Remove this skin? This cannot be undone.',
    skinsRemoving: 'Removing...',
    skinsRemoveOk: 'Remove',
    skinsCancel: 'Cancel',
    skinsImport: 'Import Skin',
    skinsGuideFormat: 'Format Guide',
    skinsFormat: 'Format',
    skinsFormatVal: 'Sprite Sheet (PNG)',
    skinsRequired: 'Required',
    skinsRequiredVal: 'skin.json + sprite + pet.png',
    skinsPetPng: 'pet.png',
    skinsPetPngVal: 'Avatar (pet.gif supported)',
    skinsStates: 'States',
    skinsStatesVal: 'idle, walk, run, sprint',
    skinsSkinJson: 'skin.json',
    skinsSkinJsonVal: 'name, author, format, size, animations',
    skinsOptional: 'Optional',
    skinsOptionalVal: 'source (URL), license',
    skinsDownloadExample: 'Download Example',
    skinsImportFolder: 'Import Folder',
    skinsImportZip: 'Import ZIP',
    skinsSelectFolder: 'Select skin folder',
    skinsSelectZip: 'Select skin archive',
    skinsZipFilter: 'Archives',
    skinsRemoveBtn: 'Remove Skin',

    settingsTitle: 'Settings',
    settingsProfile: 'Profile',
    settingsNickname: 'Nickname',
    settingsNicknamePlaceholder: 'Enter nickname',
    settingsGeneral: 'General',
    settingsTheme: 'Appearance',
    settingsThemeHint: 'Panel color scheme',
    settingsThemeLight: 'Light',
    settingsThemeDark: 'Dark',
    settingsThemeSystem: 'System',
    settingsShowOverFullscreen: 'Show Over Fullscreen',
    settingsShowOverFullscreenHint: 'Keep the pet visible when other apps are fullscreen',
    settingsAutoStart: 'Launch at Login',
    settingsAutoStartHint: 'Start AIbubu when you log in',
    updateTitle: 'Updates',
    updateCheck: 'Check for Updates',
    updateUpToDate: 'You are on the latest version',
    updateChecking: 'Checking...',
    updateNewVersion: 'New version available',
    updateDownloading: 'Downloading update...',
    updateReadyRestart: 'Download complete, restart to update',
    updateCheckBtn: 'Check',
    updateDownloadBtn: 'Download',
    updateRestartBtn: 'Restart',

    settingsLan: 'LAN Discovery',
    settingsLanHint: 'Let teammates on the same network find you',

    about: 'About',
    aboutDesc: 'A coding step counter for the AI era',
    aboutVersion: 'Version',
    aboutDeveloper: 'Developer',
    aboutWebsite: 'Website',
    aboutGitHub: 'GitHub',
    aboutGitHubHint: 'Like it? Give us a Star on GitHub',
    aboutPrivacy: 'Privacy',
    aboutPrivacyHint: 'All data is stored locally and never uploaded to any server',
    aboutPrivacyPolicy: 'Privacy Policy',
    aboutLicense: 'License',
    aboutFeedback: 'Feedback',
    aboutFeedbackHint: 'Found a bug or have an idea? Open an Issue',

    connected: ' online',
    disconnected: 'Offline',
    disconnectedHint: 'Go to settings to enable LAN discovery',

    trayShow: 'Show Pet',
    trayHide: 'Hide Pet',
    trayLeaderboard: 'Leaderboard',
    trayQuit: 'Quit',

    steps: ' steps',
    anonymous: 'Anonymous',
    skinCannotRemove: 'Built-in skins cannot be removed',
    skinRemoveFail: 'Failed to remove',
    skinImportFail: 'Import failed',
    dragHint: 'Hold to drag',

    statsTitle: 'Insights',
    statsWeekTrend: '7-Day Trend',
    statsMonthTrend: '30-Day Trend',
    statsHeatmap: 'Active Hours',
    statsHeatmapHint: '24h activity distribution',
    statsProviders: 'Tool Usage',
    statsProvidersHint: 'Activity share by AI tool',
    statsStreak: 'Streak',
    statsStreakDays: 'd',
    statsNoData: 'No data yet',
    statsSteps: ' steps',
    historyDetailHourly: 'Hourly',
    historyDetailProviders: 'Tools',
    historyNoDetail: 'No detail data',

    moodNormal: '',
    moodSleepy: '💤',
    moodExcited: '🔥',
    moodHappy: '😊',
    interactHint: 'Click to interact · Right-click for menu',
  },
}

export type MessageKey = keyof typeof messages.zh

export function useI18n() {
  const lang = currentLang

  function setLang(l: Lang) {
    lang.value = l
    try {
      localStorage.setItem(LANG_KEY, l)
    } catch {
      /* noop */
    }
  }

  function t(key: MessageKey): string {
    return messages[lang.value][key] ?? messages.zh[key] ?? key
  }

  const isZh = computed(() => lang.value === 'zh')

  return { lang, setLang, t, isZh }
}
