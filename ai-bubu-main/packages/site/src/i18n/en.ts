export default {
  site: {
    title: 'AIbubu — A Coding Step Counter for the AI Era',
    description:
      'Track your AI coding tool activity (Cursor, Claude Code, Codex, OpenCode, Trae) and watch your desktop pet run. Free and open source.',
  },
  nav: {
    brand: 'AIbubu',
    switchLang: '中',
    backHome: 'Back to Home',
  },
  hero: {
    titleLine1: 'A step counter',
    titleLine2: 'for the AI era',
    desc: "Your AI coding activity drives your pet's steps and moves — run with your team",
    downloadMac: 'Download for macOS',
    downloadWin: 'Download for Windows',
    downloadLinux: 'Download for Linux',
    allPlatforms: 'All Platforms',
    versionPrefix: 'v{ver} · ',
    betaPrefix: 'Beta · ',
    toolList: 'Supports Cursor, Claude Code, Codex, OpenCode, Trae & more',
    demoVideo: '/demo/demo_en.mp4',
  },
  states: {
    walk: {
      title: 'It walks',
      desc: 'Quietly keeping<br />you company',
      alt: 'Desktop pet walking animation',
    },
    run: {
      title: 'It runs',
      desc: 'More AI activity<br />means more speed',
      alt: 'Desktop pet running animation',
    },
    sprint: {
      title: 'It sprints',
      desc: 'Full speed<br />coding mode',
      alt: 'Desktop pet sprinting animation',
    },
    together: {
      title: 'Run together',
      desc: 'Auto-discover on LAN<br />compete with teammates',
      alt: 'Multiple desktop pets running together on LAN',
    },
  },
  features: {
    title: 'Features',
    slides: [
      {
        img: '/screenshot/today_en.jpg',
        alt: 'AIbubu today view: steps, activity and peak stats',
        title: 'Today',
        desc: 'Steps, activity, peak — your coding pulse at a glance',
      },
      {
        img: '/screenshot/rank_en.jpg',
        alt: 'AIbubu leaderboard: LAN teammate step rankings',
        title: 'Leaderboard',
        desc: 'Auto-discover teammates, see who runs the farthest',
      },
      {
        img: '/screenshot/pet_en.jpg',
        alt: 'AIbubu character picker: multiple pixel pets to choose',
        title: 'Pick a buddy',
        desc: '8 pixel pals, custom skins supported',
      },
      {
        img: '/screenshot/setting_en.jpg',
        alt: 'AIbubu settings: name, theme and auto-start options',
        title: 'Make it yours',
        desc: 'Name, theme, auto-start — fully yours',
      },
      {
        img: '/screenshot/about_en.jpg',
        alt: 'AIbubu about view: version info, privacy and feedback',
        title: 'About',
        desc: 'Updates, privacy, feedback — all in one place',
      },
    ],
  },
  chars: {
    title: 'Pick your companion',
    note: 'Custom skins supported · More on the way',
  },
  footer: {
    credits: 'Pixel art by',
    privacy: 'Privacy',
    copyright: '© 2026 aibubu.app',
  },
  download: {
    title: 'Download AIbubu',
    pageTitle: 'Download AIbubu — macOS / Windows / Linux',
    description: 'Free download AIbubu desktop pet for macOS, Windows, and Linux.',
    subtitle: 'Choose the version for your system',
    githubLink: 'View all releases on GitHub',
    platforms: {
      macArm: { label: 'macOS (Apple Silicon)', desc: 'For Mac with M1 / M2 / M3 / M4 chip' },
      macIntel: { label: 'macOS (Intel)', desc: 'For Mac with Intel chip' },
      win: { label: 'Windows', desc: 'Windows 10 and above' },
      linux: { label: 'Linux', desc: 'AppImage format, supports most distributions' },
    },
  },
  privacy: {
    pageTitle: 'Privacy Policy — AIbubu',
    description:
      'AIbubu privacy policy. All data is stored locally on your device. Nothing is uploaded.',
  },
  jsonLd: {
    description: 'A desktop pet that tracks your AI coding tool activity and turns it into steps.',
    screenshot: 'https://aibubu.app/screenshot/today_en.jpg',
  },
} as const
