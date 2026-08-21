# Frontend Refactor — Phase 1 完成记录

> Decision Record: Settings React Island 迁移 + Semi Design 引入 + FOUC 防御

## 已完成工作

### Phase 0: 脚手架 (已 commit)
- Vite 6 + React 18 + TypeScript 构建体系
- `static/app.js` 通过 ES module side-effect import 纳入 Vite 模块图
- `public/` 目录存放非打包资源（fonts, vendor libs）
- Tauri v2 配置指向 Vite dev/build 产出

### Phase 1: Settings React Island
第一个 React Island——Settings 弹窗，从 vanilla DOM 迁移为 React + Semi Design 组件。

**架构：**
```
app.js (openSettings → dispatch 'ga:open-settings')
        ↓ CustomEvent
SettingsModal.tsx (监听事件 → 打开 Modal)
        ↓ Zustand store
各 Section 组件 (读/写 store → 调 bridge/legacy service)
        ↓
bridge.ts (window.ga.* → HTTP API)    |  legacy.ts (window.gaLegacy.*)
```

**组件库选择：Semi Design（@douyinfe/semi-ui）**
- 最初选用 TDesign，后切换为 Semi Design
- 理由：Semi 按需加载更优（不需要全局 CSS import）、字节生态更熟悉、Bundle 更小
- 产出对比：TDesign 全量引入 622KB → Semi 按需 564KB（gzip 178KB）

**迁移的功能区块：**
1. 外观切换（light/dark RadioGroup）
2. 字体大小（Slider 10-20px）
3. 语言切换（zh/en RadioGroup）
4. 模型管理（列表 + 添加/编辑/删除 Modal）
5. 功能区（导入/导出 mykey、服务管理跳转）

**简化决策：**
- 去掉 plain mode（简洁模式）——使用率极低，增加代码复杂度
- 去掉语言国旗 SVG——视觉噪音，文字已足够

### FOUC 三层防御
1. `<link rel="stylesheet" href="/styles.css">` in `<head>` — 同步阻塞渲染
2. `public/styles.css` → symlink to `../static/styles.css` — 保证 dev/prod 一致
3. `<body class="no-transition">` + `setTimeout` 移除 — 抑制首次 paint 的 transition

### Dev Mock
`services/bridge.ts` 在 bridge 不可用时返回 mock 数据，允许纯前端开发（无需启动 Python bridge）。

## 技术栈

| 层 | 选择 |
|----|------|
| 构建 | Vite 6 |
| UI 框架 | React 18 |
| 组件库 | Semi Design 2.x (@douyinfe/semi-ui) |
| 状态管理 | Zustand 5 |
| 类型 | TypeScript 5.6 |
| 测试 | Vitest + Testing Library (待补) |

## 文件结构

```
frontends/desktop/
├── src/
│   ├── main.tsx                    # 入口：import CSS/app.js → mount React
│   ├── components/settings/
│   │   ├── SettingsModal.tsx       # Semi Modal 壳
│   │   ├── AppearanceSection.tsx   # 外观 RadioGroup
│   │   ├── FontSizeSection.tsx     # 字体 Slider
│   │   ├── LanguageSection.tsx     # 语言 RadioGroup
│   │   ├── ModelSection.tsx        # 模型列表 + CRUD
│   │   ├── AddModelModal.tsx       # 添加/编辑模型表单
│   │   ├── FeatureSection.tsx      # mykey 导入导出 + 服务管理
│   │   └── settings.css           # Settings 专用样式
│   ├── services/
│   │   ├── bridge.ts              # window.ga.* 封装 + dev mock
│   │   └── legacy.ts             # window.gaLegacy.* 过渡桥接
│   └── stores/
│       └── settings.ts            # Zustand store
├── static/
│   ├── app.js                     # 6200行老代码（暴露 gaLegacy, openSettings 改事件派发）
│   └── styles.css                 # 全局样式
├── public/
│   ├── styles.css → ../static/styles.css  # symlink for FOUC prevention
│   ├── vendor/marked.min.js
│   ├── phosphor-icons.js
│   └── assets/fonts/
├── index.html                     # Vite 入口 HTML
├── vite.config.ts
├── tsconfig.json
└── package.json
```

## 下一步 (Phase 2)

- Chat 页消息渲染迁移为 React 组件
- 直接 fetch bridge HTTP API 替代 window.ga.* 间接调用
- 添加 Vitest 单元测试
- Semi Design 主题定制（暗色模式 token 对齐）
- Bundle 优化（manualChunks 拆分 app.js 和 Semi）
