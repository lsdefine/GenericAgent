# BUG-002: 页面刷新时图标闪屏 (FOUC)

## 状态: ✅ 已修复

## 现象

刷新 GA 页面时，侧边栏图标以巨大尺寸（~1262×1262px）闪现约 50-200ms，随后缩小到正常的 16×16px。造成明显的视觉闪屏。

## 根因

经典的 FOUC（Flash of Unstyled Content）问题，由 CSS 加载时序导致：

### 加载时间线

```
[1] HTML <head> 解析   → 只加载 fonts.css（字体定义）、katex、hljs 等第三方 CSS
[2] HTML <body> 解析   → 浏览器开始渲染侧边栏 HTML 结构
[3] phosphor-icons.js  → 同步脚本，立即将 <span data-ga-icon> 替换为 SVG
                         SVG 属性: viewBox="0 0 256 256", 无 width/height
[4] main.tsx (module)  → type="module" 异步加载
[5] import styles.css  → Vite 将 CSS 注入 <style> 标签到 <head>
                         此时 .ic{width:16px;height:16px} 才生效
```

**闪屏窗口 = 步骤 [3] 到 [5] 的时间差**

### 关键证据

| 状态 | SVG.ic 计算尺寸 |
|------|----------------|
| 无 styles.css（模拟闪屏）| 1262 × 1262 px |
| styles.css 加载后 | 16 × 16 px |

### 问题代码

**文件**: `static/phosphor-icons.js` line 81

```javascript
// gaIcon() 生成的 SVG 无 width/height 属性
return `<svg${cls} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true" focusable="false"><path d="${d}"/></svg>`;
```

**文件**: `src/main.tsx` line 2

```typescript
// styles.css 通过 JS 模块异步加载
import '../static/styles.css';
```

## 修复方案

**推荐方案：给 SVG 添加内联尺寸属性**

```javascript
// static/phosphor-icons.js line 81 修改为：
return `<svg${cls} xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true" focusable="false"><path d="${d}"/></svg>`;
```

使用 `1em` 而非固定 `16px` 的优势：
- 图标大小随字体上下文自适应
- 不需要为每个使用场景硬编码尺寸
- CSS 加载后仍可覆盖（CSS 优先级高于 HTML 属性）

**备选方案：在 `<head>` 内联关键 CSS**

```html
<!-- index.html <head> 中添加 -->
<style>
  .ic { width: 16px; height: 16px; display: inline-block; vertical-align: middle; }
  svg.ic { width: 16px; height: 16px; }
</style>
```

## 验证方法

1. 应用修复后硬刷新页面 (Cmd+Shift+R)
2. 使用 Chrome DevTools Performance → 录制页面加载
3. 在 "First Paint" 帧中确认图标未出现巨大尺寸
4. 模拟慢网络 (3G throttling) 验证极端情况

### 自动化测试思路

```javascript
// playwright e2e test
test('no icon FOUC on page load', async ({ page }) => {
  // Intercept to slow down module loading
  await page.route('**/src/main.tsx', route =>
    new Promise(resolve => setTimeout(() => resolve(route.continue()), 200))
  );

  await page.goto('/');

  // Capture icon sizes immediately
  const iconSizes = await page.evaluate(() => {
    const svgs = document.querySelectorAll('svg.ic');
    return [...svgs].map(s => ({
      w: s.getBoundingClientRect().width,
      h: s.getBoundingClientRect().height
    }));
  });

  // All icons should be <= 20px even before styles fully load
  for (const size of iconSizes) {
    expect(size.w).toBeLessThanOrEqual(20);
    expect(size.h).toBeLessThanOrEqual(20);
  }
});
```

## 分类

- **类型**: FOUC / CSS 加载时序
- **严重级**: P3 (视觉瑕疵，不影响功能)
- **影响范围**: 所有用户每次刷新页面
- **前端常见度**: 非常常见，Vite/Webpack 通过 JS import CSS 的模式天然存在此问题
