# Insight #001: FOUC 与 CSS 加载时序

> 项目发现 → 通用工程原则

## 项目背景

GenericAgent Desktop 前端在刷新时出现严重闪屏：裸 HTML 内容（大尺寸图标、无样式布局）先渲染约 200-500ms，然后 CSS 加载后突然跳变为正确样式。

## 根因分析

### 直接原因

Vite dev 模式下，`styles.css` 仅通过 ES module 的 `import '../static/styles.css'` 加载。ES module 是**异步非阻塞**的 — 浏览器解析完 `<body>` 后立即开始渲染，不会等待 module 中的 CSS 注入完成。

```
时间线（有问题）:
[HTML解析] → [body首次渲染(无样式)] → [module加载] → [CSS注入] → [重绘(有样式)]
                    ↑ 闪屏发生在这里
```

### 对比：生产版为什么没问题

生产版 `static/index.html` 使用 `<link rel="stylesheet" href="styles.css">` 同步加载。`<link>` 标签是 **render-blocking** 的 — 浏览器会等 CSS 下载完成后再渲染 body。

```
时间线（正确）:
[HTML解析] → [等待CSS下载] → [body首次渲染(有样式)]
```

### 闪屏的三个维度

| 维度 | 表现 | 根因 |
|------|------|------|
| FOUC | 无样式内容闪现 | CSS 异步加载 |
| 图标尺寸跳变 | SVG 从巨大尺寸缩到正常 | SVG 缺少内联 width/height，依赖 CSS 约束 |
| 过渡动画 | 元素从初始态"飘"到最终位置 | CSS transition 捕获了无样式→有样式的变化 |

## 修复方案

三层防御：

1. **同步 CSS 加载** — `<head>` 中添加 `<link rel="stylesheet" href="/styles.css">` 阻塞渲染
2. **内联 SVG 尺寸** — 所有 SVG 模板添加 `width="1em" height="1em"` 确保无 CSS 时也有合理尺寸
3. **no-transition 保护** — `body.no-transition` 在启动时禁用所有 transition，JS 执行后移除

## 推广：通用工程原则

### 1. 开发环境与生产环境的 CSS 加载差异

现代打包工具（Vite、Webpack dev server）通常将 CSS 作为 JS module 的副作用注入，与生产构建的行为不同：

| 环境 | CSS 加载方式 | 阻塞渲染？ |
|------|-------------|-----------|
| 生产 (link tag) | HTTP request → CSSOM → render | ✅ 阻塞 |
| Vite dev (import) | JS module → style injection → repaint | ❌ 不阻塞 |
| Webpack dev (style-loader) | JS → `<style>` 注入 | ❌ 不阻塞 |

**教训：如果 HTML 中有可见内容（非 SPA 空白骨架），必须确保关键 CSS 在开发模式下也同步加载。**

### 2. SVG 图标的防御性尺寸

SVG 没有 `width`/`height` attribute 时，浏览器会使用 `viewBox` 的固有尺寸或默认 300x150。如果图标尺寸完全依赖 CSS class，那在 CSS 加载前就会「爆炸」。

**原则：所有内联 SVG 图标应有 `width` 和 `height` attribute 作为 fallback，即使 CSS 会覆盖它们。**

### 3. CSS Transition 是双刃剑

Transition 监听的是属性值的**变化**。从无样式到有样式的首次 paint，如果恰好有 transition 属性，浏览器会将其视为一次合法的状态变化并执行动画。

**原则：对于首屏元素，使用 `no-transition` 启动保护 pattern — body 初始带一个禁用所有 transition 的 class，在首次 paint 稳定后移除。**

```css
body.no-transition,
body.no-transition * {
  transition: none !important;
}
```

### 4. opacity:0 隐藏方案的陷阱

一种常见的 FOUC 修复是在 `<head>` 中设 `body { opacity: 0 }` 然后 JS 中移除。但这本身引入了新的感知问题：

- 用户看到空白屏 → 突然出现完整内容（「闪现」）
- 如果 JS 执行延迟（网络慢、大 bundle），页面会长时间空白
- 本质是用「白屏」替代了「乱屏」，体验不一定更好

**更好的方案：直接消除问题根源（同步加载 CSS），而不是隐藏症状。**

### 5. 开发模式的 FOUC 是否值得修

值得。原因：
- 开发者每天刷新数百次，FOUC 影响开发体验和 debug 效率
- FOUC 可能掩盖真实的样式 bug（误以为是加载问题而忽略）
- 如果开发模式和生产模式的 CSS 加载行为不一致，可能漏掉生产环境的问题

## 检测清单

对任何有预渲染 HTML 的前端项目（非纯 SPA 空白容器）：

- [ ] 关键 CSS 是否通过 `<link>` 在 `<head>` 中同步加载？
- [ ] 开发模式（dev server）和生产模式的 CSS 时序是否一致？
- [ ] 内联 SVG 是否有 width/height fallback？
- [ ] 首屏元素是否有 transition 保护？
- [ ] 禁用 JavaScript 后页面是否有基本可读性？（CSS 不应完全依赖 JS）

---

*发现日期: 2026-06-30*
*项目: GenericAgent Desktop Frontend (Vite + React)*
