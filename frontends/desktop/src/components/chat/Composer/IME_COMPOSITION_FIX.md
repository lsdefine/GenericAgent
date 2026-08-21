---
title: IME Composition 与 Enter 键冲突
scope: frontends/desktop (React)
date: 2026-07-06
status: resolved
---

# 问题：拼音输入法按回车直接发送，而非选词

## 现象

在 Composer textarea 中使用拼音输入法（或其他 CJK IME）时，按 Enter 本应确认候选词，但被 `handleKeyDown` 拦截并触发了消息发送。

## 根因

`keydown` 事件的 Enter 监听没有排除 IME 组合态（composition state）。当 IME 正在组合时，浏览器仍会触发 `keydown` 事件，`e.key` 仍为 `'Enter'`，但此时的 Enter 语义是"确认候选词"而非"提交表单"。

## 关键 API

| API | 说明 |
|-----|------|
| `KeyboardEvent.isComposing` | W3C 标准属性，`true` 表示当前按键事件发生在 compositionstart 和 compositionend 之间 |
| `KeyboardEvent.keyCode === 229` | 旧式判断：组合态中所有按键的 keyCode 都为 229（兼容性 fallback） |
| `compositionstart` / `compositionend` 事件 | 可以手动维护一个 `isComposing` ref 作为 polyfill |

React 的 SyntheticEvent 不直接暴露 `isComposing`，需要通过 `e.nativeEvent.isComposing` 访问。

## 修复

```tsx
// Composer/index.tsx — handleKeyDown
if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
  e.preventDefault();
  handleSend();
}
```

一个条件判断即可。`isComposing` 在所有现代浏览器（Chrome 56+, Firefox 65+, Safari 10.1+, Edge 79+）中已稳定支持，不需要 polyfill。

## 适用范围

任何监听 Enter 键做"提交"动作的 input/textarea 都需要此保护。项目中如有其他类似逻辑（collab composer、搜索框等），应统一加上 `!e.nativeEvent.isComposing` 检查。

## 参考

- [MDN: KeyboardEvent.isComposing](https://developer.mozilla.org/en-US/docs/Web/API/KeyboardEvent/isComposing)
- [W3C UI Events: composition events](https://www.w3.org/TR/uievents/#events-compositionevents)
