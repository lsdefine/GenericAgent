export default {
  site: {
    title: 'AI 步步 — AI 时代的编码计步器',
    description:
      '实时监测 Cursor、Claude Code、Codex、OpenCode、Trae 等 AI 工具的使用量，化为桌面宠物的步数和动作。',
  },
  nav: {
    brand: 'AI 步步',
    switchLang: 'EN',
    backHome: '返回首页',
  },
  hero: {
    titleLine1: 'AI 时代的',
    titleLine2: '编码计步器',
    desc: '你的 AI 编码活动，化为桌面宠物的步数和动作——还能和同事一起跑',
    downloadMac: '下载 macOS 版',
    downloadWin: '下载 Windows 版',
    downloadLinux: '下载 Linux 版',
    allPlatforms: '所有平台',
    versionPrefix: 'v{ver} · ',
    betaPrefix: 'Beta · ',
    toolList: '支持 Cursor、Claude Code、Codex、OpenCode、Trae 等',
    demoVideo: '/demo/demo.mp4',
  },
  states: {
    walk: { title: '它会走', desc: '安安静静<br />陪你写代码', alt: '桌面宠物走路动画' },
    run: { title: '它会跑', desc: '用 AI 越多<br />跑得越快', alt: '桌面宠物跑步动画' },
    sprint: { title: '它飞奔', desc: '全力编码<br />极速冲刺', alt: '桌面宠物冲刺动画' },
    together: {
      title: '一起跑',
      desc: '局域网自动发现<br />和同事比拼步数',
      alt: '多只桌面宠物一起跑步',
    },
  },
  features: {
    title: '功能一览',
    slides: [
      {
        img: '/screenshot/today.jpg',
        alt: 'AI 步步今日数据界面：步数、活跃度、峰值',
        title: '今日数据',
        desc: '步数 · 活跃度 · 峰值，编码节奏尽在掌握',
      },
      {
        img: '/screenshot/rank.jpg',
        alt: 'AI 步步同事排行榜：局域网步数对比',
        title: '同事排行',
        desc: '局域网自动发现，看看谁今天跑得最远',
      },
      {
        img: '/screenshot/pet.jpg',
        alt: 'AI 步步角色选择界面：多款像素宠物',
        title: '挑选角色',
        desc: '8 款像素伙伴，支持自定义角色',
      },
      {
        img: '/screenshot/setting.jpg',
        alt: 'AI 步步设置界面：昵称、主题、自启动',
        title: '自由定制',
        desc: '昵称 · 主题 · 自启动，一切由你做主',
      },
      {
        img: '/screenshot/about.jpg',
        alt: 'AI 步步关于界面：版本信息、隐私政策、反馈',
        title: '关于',
        desc: '版本更新 · 隐私保护 · 意见反馈',
      },
    ],
  },
  chars: {
    title: '挑选你的伙伴',
    note: '支持自定义角色 · 更多角色持续更新中',
  },
  footer: {
    credits: '像素角色来自',
    privacy: '隐私协议',
    copyright: '© 2026 aibubu.app',
  },
  download: {
    title: '下载 AI 步步',
    pageTitle: '下载 AI 步步 — macOS / Windows / Linux',
    description: '免费下载 AI 步步桌面宠物，支持 macOS、Windows、Linux 三大平台。',
    subtitle: '选择适合你系统的版本',
    githubLink: '在 GitHub 查看所有版本',
    platforms: {
      macArm: { label: 'macOS (Apple Silicon)', desc: '适用于 M1 / M2 / M3 / M4 芯片的 Mac' },
      macIntel: { label: 'macOS (Intel)', desc: '适用于 Intel 芯片的 Mac' },
      win: { label: 'Windows', desc: 'Windows 10 及以上' },
      linux: { label: 'Linux', desc: 'AppImage 格式，支持大多数发行版' },
    },
  },
  privacy: {
    pageTitle: '隐私政策 — AI 步步',
    description: 'AI 步步的隐私政策，所有数据仅存储在本地，不上传任何信息。',
  },
  jsonLd: {
    description: '一款桌面宠物，追踪你的 AI 编码工具使用量并转化为步数。',
    screenshot: 'https://aibubu.app/screenshot/today.jpg',
  },
} as const
