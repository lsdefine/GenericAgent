# BUG-001: Settings 弹窗点击崩溃

## 状态: ✅ 已修复

## 现象

点击侧边栏底部 Settings 按钮时，整个应用白屏/无响应，控制台报错 `TypeError: Cannot read properties of undefined`。

## 根因

`src/components/settings/ModelSection.tsx` 中 `profileLabel` 变量在 `selectedProfile` 为 `undefined` 时尝试访问 `.name` 属性，导致 React 渲染崩溃。

```typescript
// 修复前
const profileLabel = profiles.find(p => p.id === selectedProfile).name;

// 修复后
const profileLabel = profiles.find(p => p.id === selectedProfile)?.name ?? 'Default';
```

## 触发条件

- 用户首次使用或 localStorage 中无已保存的 profile 选择
- `selectedProfile` state 为 `undefined`，`.find()` 返回 `undefined`
- 直接对 `undefined` 取 `.name` → 抛出 TypeError

## 修复文件

- `src/components/settings/ModelSection.tsx`：添加可选链 + 空值合并

## 验证方法

1. 清除 localStorage 中 `ga-selected-profile` 项
2. 刷新页面
3. 点击 Settings 按钮
4. 预期：弹窗正常打开，profile 显示为 "Default"

## 回归测试建议

```typescript
// vitest unit test
describe('ModelSection', () => {
  it('should render without crash when selectedProfile is undefined', () => {
    render(<ModelSection profiles={mockProfiles} selectedProfile={undefined} />);
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  it('should display correct profile name when selectedProfile is valid', () => {
    render(<ModelSection profiles={mockProfiles} selectedProfile="profile-1" />);
    expect(screen.getByText('My Profile')).toBeInTheDocument();
  });
});
```

## 分类

- **类型**: Runtime crash / Null safety
- **严重级**: P1 (功能完全不可用)
- **影响范围**: 所有未预设 profile 的用户
