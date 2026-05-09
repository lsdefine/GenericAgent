# Vue 3 自定义组件 JS 操作 SOP

## 问题
Vue 3 自定义组件（如 OxdSelect）通过 `addEventListener` 绑定事件，JS `dispatchEvent` 产生的事件 `isTrusted: false`，组件不响应。
- `element.click()` 无效（组件可能绑定 mousedown 而非 click）
- `dispatchEvent(new MouseEvent('mousedown'))` 无效（isTrusted:false）
- `element.focus()` 不触发 Vue 绑定的 focus handler

## 解决方案：直接操作 Vue 组件实例

### 1. 获取 Vue 3 根入口
```javascript
const rootVnode = document.getElementById('app')._vnode;
```

### 2. 遍历 vnode 树匹配 DOM 元素
```javascript
function findCompByEl(vnode, targetEl, depth = 0) {
    if (depth > 50 || !vnode) return null;
    const comp = vnode.component;
    if (comp) {
        if (comp.vnode?.el === targetEl || comp.subTree?.el === targetEl) return comp;
        if (comp.vnode?.el?.contains?.(targetEl)) {
            const result = findCompByEl(comp.subTree, targetEl, depth + 1);
            if (result) return result;
            return comp;
        }
        const subResult = findCompByEl(comp.subTree, targetEl, depth + 1);
        if (subResult) return subResult;
    }
    if (vnode.children && Array.isArray(vnode.children)) {
        for (const child of vnode.children) {
            const result = findCompByEl(child, targetEl, depth + 1);
            if (result) return result;
        }
    }
    if (vnode.dynamicChildren) {
        for (const child of vnode.dynamicChildren) {
            const result = findCompByEl(child, targetEl, depth + 1);
            if (result) return result;
        }
    }
    return null;
}
```

### 3. 调用组件方法
```javascript
// 目标DOM的parentElement通常是组件根元素
const comp = findCompByEl(rootVnode, targetElement.parentElement);
const ctx = comp.proxy;

// 查看可用方法
Object.keys(ctx).filter(k => !k.startsWith('_') && !k.startsWith('$'));

// Select 类组件：直接调用 onSelect
ctx.onSelect({id: 'USD', label: 'United States Dollar'});

// 获取选项列表
ctx.computedOptions; // [{id, label, _selected}, ...]
```

## 组件层级注意
- **展示层**（如 OxdSelectText）：只有 onToggle/onFocus/onBlur，调用无实际效果
- **逻辑层**（如 OxdSelectInput，是展示层的父组件）：有 openDropdown/onSelect/computedOptions/onCloseDropdown
- 定位逻辑层：用 `targetElement.parentElement` 而非 targetElement 本身

### 弹窗内 Select 同样纯 JS 优先（已验证）
- 弹窗（`.oxd-dialog-sheet`）内的 `.oxd-select-text` 用循环向上查找同样能命中 `OxdSelectInput`，`onSelect` 正常工作。
- 不需要 CDP 兜底。仅当循环 8 层仍找不到组件时才考虑 CDP 打开+JS 点 option。

### 循环向上查找模式（推荐）
单层 `parentElement` 可能不够，用循环更健壮：
```javascript
function findSelectComp(selectTextEl) {
  for (let el = selectTextEl, up = 0; el && up < 8; el = el.parentElement, up++) {
    const comp = findCompByEl(rootVnode, el);
    if (comp?.proxy?.onSelect && comp.proxy.computedOptions?.length) return comp;
  }
  return null; // 找不到再考虑CDP兜底
}
```

## 普通 Input/Textarea 操作（nativeSetter）

Vue 3 的 `v-model` 监听 input 事件，直接 `el.value = x` 不触发响应式。需用原型 setter：

```javascript
// Input
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
setter.call(inputEl, '新值');
inputEl.dispatchEvent(new Event('input', {bubbles: true}));
inputEl.dispatchEvent(new Event('change', {bubbles: true}));

// Textarea
const taSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
taSetter.call(textareaEl, '内容');
textareaEl.dispatchEvent(new Event('input', {bubbles: true}));
```

### Date Input 特殊处理
日期组件通常有 blur 校验，需要 focus→赋值→blur 完整链：
```javascript
dateInput.focus();
setter.call(dateInput, '2026-08-05');
dateInput.dispatchEvent(new Event('input', {bubbles: true}));
dateInput.dispatchEvent(new Event('change', {bubbles: true}));
dateInput.dispatchEvent(new Event('blur', {bubbles: true}));
```

### Button
普通 `.click()` 即可，Vue 3 不检查 button click 的 isTrusted。

### File Upload (input[type="file"])
浏览器安全模型禁止JS直接 `input.value='path'`，但可用 DataTransfer API 构造 FileList：
```javascript
const fileInput = document.querySelector('input[type="file"]');
const content = '文件内容';
const file = new File([content], 'filename.txt', { type: 'text/plain', lastModified: Date.now() });
const dt = new DataTransfer();
dt.items.add(file);
fileInput.files = dt.files;  // Chrome 62+ 支持
fileInput.dispatchEvent(new Event('input', { bubbles: true }));
fileInput.dispatchEvent(new Event('change', { bubbles: true }));
```
- 适用于任何框架（非Vue3特有），纯浏览器API
- 可构造任意类型文件（Blob/ArrayBuffer均可传入File构造器）
- ⚠ CDP `DOM.setFileInputFiles` 只设files属性不触发事件（Chrome通用行为），DataTransfer+dispatch是唯一纯JS方案
- ⚠ 确保弹窗/容器已打开再querySelector，否则input不在DOM中

## 泛化到其他 Vue3 站点（未逐一验证，思路层面）

本 SOP 的核心方法（根 vnode → findCompByEl → proxy）是 Vue3 通用的，但具体方法名/属性名因 UI 库而异。

面对陌生 Vue3 站点的探测思路：

1. **确认是 Vue3** — `document.getElementById('app')?.__vue_app__` 存在即可
2. **定位目标 DOM** — 用选择器找到要操作的元素（如某个 select wrapper）
3. **从 DOM 反查组件** — 用 findCompByEl 从目标元素及其父级向上找，拿到 component
4. **探测组件能力** — 拿到 comp 后查看：
   - `Object.keys(comp.proxy.$options.methods || {})` → 组件方法名
   - `Object.keys(comp.props || {})` → props
   - `Object.keys(comp.setupState || {})` → setup 暴露的响应式数据和函数
   - 重点找类似 onSelect/handleSelect/select/setValue 的方法，以及 options/items/computedOptions 之类的选项列表
5. **试调** — 找到疑似选中方法后，传入选项对象试调，观察 DOM 是否更新
6. **选项格式** — 不同库的 option 结构不同（可能是 `{id, label}` 也可能是 `{value, text}` 或纯字符串），从选项列表数据中取一个完整对象传入即可

注意事项：
- 有些库用 `emits` 而非 methods，选中逻辑可能在父组件而非子组件
- 有些库 prod build 会 minify 方法名，此时 setupState 里的 key 可能是短名，需结合行为猜测
- Composition API 组件的逻辑主要在 setupState 而非 $options.methods
- 如果 proxy 上找不到方法，试试 `comp.exposed`（`<script setup>` 用 defineExpose 暴露的）

## Vue 富文本编辑器操作

### 核心原则
1. **禁止只改 DOM** — `innerHTML` 不触发编辑器内部 model 更新，提交时数据丢失
2. **优先找编辑器实例调原生 API** — 唯一稳路径：
   - Quill: `el.__quill.setText()` / `.clipboard.dangerouslyPasteHTML()`
   - Tiptap: `el.__tiptap.commands.setContent()` 或 Vue ref `.editor.commands.setContent()`
   - TinyMCE: `tinymce.get(id).setContent()` 或 `tinymce.activeEditor.setContent()`
   - WangEditor: `el.__wangEditor.setHtml()` 或 Vue ref `.editorRef.setHtml()`
   - CKEditor: `editor.setData()`
3. **次选 `innerHTML + InputEvent`** — 对简单 Vue wrapper 有效（wrapper 监听 input 并 emit），复杂编辑器不保证
4. **兜底 CDP `Input.insertText`** — 绕过 `isTrusted` 检查，等同物理输入
5. **验证标准是"提交对了"不是"看到了"** — 拦截 fetch/XHR 看 payload，或读 `editor.getHTML()`

### 编辑器实例查找路径（按优先级）
1. DOM 私有字段: `el.__quill`, `el.__tiptap`, `el.cmView`(CodeMirror)
2. Vue 组件 setupState/exposed: `comp.setupState.editor`, `comp.exposed.editor`
3. 全局变量: `window.editor`, `tinymce.editors[0]`
4. Quill 静态方法: `Quill.find(el)`

### 编辑器类型识别
- `.ql-editor` → Quill
- `.ProseMirror` → Tiptap / ProseMirror
- `.tox-edit-area` / `iframe` → TinyMCE
- `.w-e-text-container` → WangEditor
- `.ck-editor__editable` → CKEditor 5
- `.cm-editor` → CodeMirror 6

### 避坑
- Element Plus Select 选项被 Teleport 到 body，不在组件 DOM 子树内，要从 `document.querySelectorAll('.el-select-dropdown__item')` 全局找
- 编辑器可能在 iframe 内（TinyMCE 默认），需 `iframe.contentDocument.body` 操作
- 提交时数据来源可能不是 Vue state，而是编辑器实例现取 `getHTML()`，所以必须改编辑器 model
- debounce：有些 wrapper 用 debounce 同步到 v-model，改完后等 300-500ms 再验证
- Pinia/Vuex：表单数据可能在 store 里而非组件 data，需找到 store 直接赋值

## 适用场景
- Vue 3 自定义 Select/Dropdown/Autocomplete 组件 → vnode 实例方法
- Vue 3 普通 Input/Textarea（v-model）→ nativeSetter + input 事件
- Date 组件 → nativeSetter + focus/blur 链
- File Upload → DataTransfer + change 事件
- 需要绕过 isTrusted 检查的场景
- **Vue 3 富文本编辑器（Quill/Tiptap/TinyMCE/WangEditor/CKEditor）→ 编辑器实例 API**

## 验证于
- OrangeHRM (opensource-demo.orangehrmlive.com) Vue 3 + OXD 组件库
- 本地 Vue3 + Element Plus + 模拟 Quill/Tiptap 富文本靶场 (2026-05-09)
- 2026-05-08
