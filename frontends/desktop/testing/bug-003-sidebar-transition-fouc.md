# Bug-003: Sidebar Transition FOUC on Page Load

## Problem
刷新/进入页面时，sidebar 的 CSS transition（`width 0.2s`, `padding 0.2s`, `opacity 0.15s`）在页面加载期间被触发，导致 sidebar 从初始状态动画过渡到目标状态，造成明显的视觉闪烁/FOUC。

## Root Cause
- `styles.css` 通过 Vite 的 `import '../static/styles.css'` 异步加载（ES module）
- 浏览器先渲染 HTML 默认样式，CSS 注入后 transition 属性生效
- 此时 sidebar 的 width/padding/opacity 从默认值过渡到目标值，产生动画闪烁
- 这是前端 SPA 中常见的 FOUC（Flash of Unstyled Content）变体

## Fix Applied

### 1. HTML: 添加 `no-transition` class 到 `<body>`
所有 3 个入口文件：
- `index.html` (Vite dev)
- `static/index.html` (standalone)
- `dist/index.html` (production build)

```html
<body class="no-transition">
```

### 2. CSS: 全局 transition 抑制规则
`static/styles.css` 顶部：
```css
/* === 防止页面加载时 transition 造成 FOUC === */
.no-transition,
.no-transition *,
.no-transition *::before,
.no-transition *::after {
  transition: none !important;
  animation: none !important;
}
```

### 3. JS: 加载完成后恢复 transition

**Vite dev 模式** (`src/main.tsx`)：
```typescript
import 'tdesign-react/es/style/index.css';
import '../static/styles.css';
import '../static/app.js';

setTimeout(() => {
  document.body.classList.remove('no-transition');
}, 0);
```

**Standalone/Production** (`static/index.html`, `dist/index.html`)：
```html
<script>
requestAnimationFrame(function(){ requestAnimationFrame(function(){
  document.body.classList.remove('no-transition');
}); });
</script>
```

## Verification
1. 页面加载时 `body.no-transition` 生效 → 所有 transition/animation 被禁用
2. CSS + JS 加载完成后 → class 被移除 → 交互动画恢复正常
3. 验证结果：
   - Load 时: `transition: none` ✅
   - Load 后: `transition: width 0.2s, padding 0.2s, opacity 0.15s` ✅

## Testing Steps
1. Hard refresh (Cmd+Shift+R) 页面
2. 观察 sidebar 是否有任何过渡动画（不应有）
3. 加载完成后，折叠/展开 sidebar 验证动画仍然正常工作
4. DevTools → 勾选 "Disable cache" 后刷新，重复验证

## Files Modified
- `index.html` — added `class="no-transition"` to body, removed redundant inline script
- `static/index.html` — added `class="no-transition"` to body, added removal script
- `dist/index.html` — added `class="no-transition"` to body, added removal script
- `static/styles.css` — added `.no-transition` CSS rule at top
- `src/main.tsx` — added setTimeout removal after CSS imports
