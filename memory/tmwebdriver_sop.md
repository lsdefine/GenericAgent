# TMWebDriver SOP

- 禁止import，直接用web_scan/web_execute_js工具。本文件只记录特性和坑。
- 底层：`../TMWebDriver.py`通过Chrome扩展(非Tampermonkey)接管用户浏览器（保留登录态/Cookie）
- 非Selenium/Playwright，不需调试浏览器或新数据目录
- 支撑 `web_scan`(只读DOM) / `web_execute_js`(执行JS) 等高层工具
- ⚠扩展更新后，已打开的旧tab不会自动加载新版脚本→scan/execute_js无ACK→需刷新页面或切到新tab

## 通用特性
- ✅web_execute_js**完美支持顶层await**（v0.4+），可直接`await fetch()`/`await new Promise()`等
  - ⚠使用await时需**显式`return`**才能拿到返回值（底层async包裹，不写return则返回null）
- ✅web_scan**自动穿透同源iframe**：无需手动操作，scan直接递归输出iframe内部DOM。跨域iframe则需CDP或postMessage（见下方章节）

## 限制(isTrusted)
- JS dispatch的事件`isTrusted=false`，敏感操作(文件上传/部分按钮)会被浏览器拦截
- ⭐**首选绕过：CDP桥**——CDP派发的Input事件是浏览器原生级别(isTrusted=true)，且无需前台，见下方CDP章节
- 文件上传：JS无法填充`<input type=file>`
  - ⭐首选CDP batch：getDocument→querySelector→DOM.setFileInputFiles(无需前台/物理点击)
  - 备选ljqCtrl物理点击：SetForegroundWindow→点上传按钮→FindWindow轮询对话框→输入路径→轮询关闭
- 备选：元素→屏幕物理坐标(ljqCtrl/PostMessage点击前必算)：JS一次取rect+窗口信息，公式：
  - `physX = (screenX + rect中心x) * dpr`，`physY = (screenY + chromeH + rect中心y) * dpr`
  - chromeH = outerHeight - innerHeight，dpr = devicePixelRatio
  - 注意：screenX/Y也是CSS像素，所有值先加后统一乘dpr
- 结论：读信息+普通操作用TMWebDriver；需isTrusted事件首选CDP桥；文件上传首选CDP三连(备选ljqCtrl)

## 导航
- `web_scan` 仅读当前页不导航，切换网站用 `web_execute_js` + `location.href='url'`

## Google图搜
- class名混淆禁硬编码，点击结果用 `[role=button]` div
- web_scan过滤边栏，弹出后用JS：文本`document.body.innerText`，大图遍历img按`naturalWidth`最大取src
- "访问"链接：遍历a找`textContent.includes('访问')`的href
- 缩略图：`img[src^="data:image"]`直接提取；大图src可能截断用`return img.src`

## Chrome下载PDF
场景：PDF链接在浏览器内预览而非下载
```js
fetch('PDF_URL').then(r=>r.blob()).then(b=>{
  const a=document.createElement('a');
  a.href=URL.createObjectURL(b);
  a.download='filename.pdf';
  a.click();
});
```
注意：需同源或CORS允许，跨域先导航到目标域再执行

## Chrome后台标签节流
- 后台标签中`setTimeout`被Chrome intensive throttling延迟到≥1min/次
- 扩展content script中detect_newtab的轮询(`setTimeout 150ms × 10`)会超时
- 已修复：移除脚本内轮询，改由Python侧`get_session_dict()`前后对比检测新标签
- 同理：扩展脚本中任何后台逻辑都应避免依赖setTimeout轮询

## CDP桥(tmwd_cdp_bridge扩展) ⭐首选
扩展路径：`assets/tmwd_cdp_bridge/`(需安装，含debugger权限)
⚠TID密钥：首次运行自动生成到`assets/tmwd_cdp_bridge/config.js`(已gitignore)，扩展通过manifest引用
调用：`web_execute_js` script直传JSON字符串（工具层自动识别对象格式，走WS→background.js cmd路由）
```js
// 直接传JSON字符串作为script参数，无需DOM操作
web_execute_js script='{"cmd": "cookies"}'
web_execute_js script='{"cmd": "tabs"}'
web_execute_js script='{"cmd": "cdp", "tabId": N, "method": "...", "params": {...}}'
web_execute_js script='{"cmd": "batch", "commands": [...]}'
// 返回值直接是JSON结果
```
⚠旧DOM方式(TID元素+MutationObserver)仍可用但已不推荐
单命令：`{cmd:'tabs'}` | `{cmd:'cookies'}` | `{cmd:'cdp', tabId:N, method:'...', params:{...}}`
- ⭐batch混合：`{cmd:'batch', commands:[{cmd:'cookies'},{cmd:'tabs'},{cmd:'cdp',...},...]}`
  - 返回`{ok:true, results:[...]}`，一次请求多命令，CDP懒attach复用session
  - 子命令会自动继承外层batch的tabId（如cookies命令可正确获取当前页面URL）
  - `$N.path`引用第N个结果字段(0-indexed)，如`"nodeId":"$2.root.nodeId"`
  - ⚠batch前序命令失败时后续`$N`引用拿到undefined，整条链路**静默失败不报错**，需检查返回results数组中每项的ok状态（未验证，BBS#46）
  - 典型：文件上传三连 getDocument(**depth:1**性能优化，200ms+→个位数ms)→querySelector(input[type=file])→setFileInputFiles（未验证，BBS#38）
  - ⚠nodeId路径一致性：getDocument+querySelector路径和performSearch+getSearchResults路径的nodeId**不互通**，同一batch内不可混用（未验证，BBS#45）
  - ⚠文件上传后前端框架(React/Vue)可能不感知→JS补发**两个事件**（Vue3需input事件而非仅change）（未验证，BBS#35/#39）：
    ```js
    el.dispatchEvent(new Event('input', {bubbles:true}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
    ```
    - Electron<12/旧WebView可能无InputEvent构造函数，防御性降级（未验证，BBS#42）：
      `const Ctor = typeof InputEvent !== 'undefined' ? InputEvent : Event; el.dispatchEvent(new Ctor('input', {bubbles:true}));`
    - 极端情况(框架仍不响应)：Runtime.evaluate直接访问React `__reactFiber` 或 Vue `__vue__` 触发状态更新（未验证，BBS#43）
  - ⚠上传前检查`input.accept`属性：setFileInputFiles不校验类型，但前端框架change handler会检查，不匹配会静默丢弃（未验证，BBS#38）
  - ⚠多file input定位：`DOM.querySelectorAll`返回nodeId数组，用accept/父容器类名区分用途（未验证，BBS#38/#39）
    - 框架选择器：Element UI `.el-upload__input` | Ant Design `.ant-upload input[type=file]` | Naive UI `.n-upload-trigger input[type=file]` | Dropzone `.dz-hidden-input`（未验证，BBS#39）
  - ⚠Dropzone拖拽上传：90%底层仍创建隐藏`<input type=file>`，先querySelectorAll('input[type=file]')全局扫（未验证，BBS#35/#38）
  - ⭐轻量元素存在检测：`DOM.performSearch({query:'input[type=file]'})`返回resultCount，不触发DOM树构建，轮询等待元素时避免重复getDocument（未验证，BBS#39）
    - performSearch支持三种语法：CSS选择器 / XPath(`//input[@type='file']`) / 纯文本，自动识别（未验证，BBS#41）
  - ⭐瞬态file input处理（Ant Design等框架点击上传按钮时动态创建input，上传完立即销毁）（未验证，BBS#42/#43）：
    - 方案A(批处理)：在同一batch内完成 performSearch→getSearchResults→setFileInputFiles→**discardSearchResults**，缩小input被销毁的时间窗口，discardSearchResults防searchId泄漏（未验证，BBS#46）
    - 方案B(事件监听)：`DOM.enable`后监听`DOM.childNodeInserted`事件捕获input创建瞬间，零延迟拿到nodeId
      - 前提：须先对document.body的nodeId调`DOM.requestChildNodes`，否则CDP不推送子树变更
      - ⚠`DOM.disable`会使所有已获取nodeId失效，setFileInputFiles必须在disable之前。正确时序：DOM.enable→requestChildNodes→[等事件]→setFileInputFiles→DOM.disable（未验证，BBS#45）
    - 方案C(猴子补丁兜底)：Runtime.evaluate注入MutationObserver标记新增file input，阻止框架销毁争取时间窗口
      - ⚠React/Vue用`parentNode.removeChild(node)`而非`node.remove()`，需patch `Element.prototype.removeChild`过滤`input[type=file]`（未验证，BBS#45）
      - ⚠Svelte等框架可能用`replaceChild`或`textContent=''`清空父容器间接移除，绕过removeChild补丁，极端场景性价比低建议回退方案B（未验证，BBS#46）
      - ⚠阻止销毁会内存泄漏，用完后手动清理被标记的节点（未验证，BBS#45）
      - FileList只读，最终仍需CDP setFileInputFiles
  - ⚠tabId：CDP默认sender.tab.id(当前注入页)，跨tab需显式tabId或先batch内tabs查
- CDP可用任意方法(Input/Network/DOM/Page/Runtime/Emulation等)，单条每次attach→send→detach
- ⭐跨tab无需前台：指定tabId即可操作后台标签页
- ⭐绕过isTrusted：CDP派发的Input事件是浏览器原生级别

## CDP点击完整生命周期（未验证，BBS#23）
- 通用点击需**三事件序列**：mouseMoved → mousePressed → mouseReleased（间隔50-100ms）
  - 省略mouseMoved会导致MUI Tooltip/Ant Design Dropdown等hover依赖组件失效
  - ⚠autofill释放是特例，只需mousePressed即可（见下方autofill章节）
- 坐标修正（页面有transform:scale/zoom时）：
  ```js
  var scale = window.visualViewport ? window.visualViewport.scale : 1;
  var zoom = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  var realX = x * zoom; var realY = y * zoom;
  ```
- iframe内元素CDP点击：坐标需合成 `finalX = iframeRect.x + elRect.x`
  - 跨域iframe拿不到contentDocument：
  - ⚠`Target.getTargets`/`Target.attachToTarget`在CDP桥中返回"Not allowed"(chrome.debugger权限限制)
  - ⭐**已验证方案**：`Page.getFrameTree`找iframe frameId → `Page.createIsolatedWorld({frameId})`获取contextId → `Runtime.evaluate({expression, contextId})`在iframe中执行JS
  - batch链式引用：`$0.frameTree.childFrames`遍历找url匹配的frame，`$1.executionContextId`传给evaluate
  - postMessage中继方案仅在content script已注入iframe时有效，第三方支付iframe通常无注入

## CDP文本输入（未验证，BBS#23）
- `Input.insertText({text:'...'})` — 直接插入，快，不触发keydown/keyup
- `Input.dispatchKeyEvent` — 逐键派发，慢但完整模拟
- React/Vue受控组件：先insertText，再JS手动dispatch `input`事件（input事件不检查isTrusted）
- 简单输入框用insertText够用

## CDP DOM域穿透 closed Shadow DOM（未验证，BBS#24/#25）
- `DOM.getDocument({depth:-1, pierce:true})` 穿透所有Shadow边界（含closed）
- `DOM.querySelector({nodeId, selector})` 定位 → `DOM.getBoxModel({nodeId})` 取坐标
- getBoxModel返回content八值[x1,y1,...x4,y4]，中心用**四点平均**：centerX=sum(x)/4, centerY=sum(y)/4
  - ⚠不能简化为对角线平均——元素有transform:rotate/skew时四点非矩形
- querySelector**不能跨Shadow边界写组合选择器**，需分步：先找host再在其shadow内找子元素
- ⚠nodeId在DOM变更后失效 → 用`backendNodeId`更稳定，或重新getDocument刷新
- 渲染检查：`DOM.resolveNode` → `Runtime.callFunctionOn` 检查offsetHeight>0
- 完整pipeline: getDocument(pierce) → querySelector → getBoxModel → 四点平均坐标 → Input三事件点击

## autofill获取与登录 (需 v0.4+ 脚本支持 await)
检测：web_scan输出input带`data-autofilled="true"`，value显示为受保护提示(非真实值，Chrome安全保护需点击释放)
- ⚠**前置条件：必须先CDP `Page.bringToFront` 切tab到前台**，Chrome仅在前台tab释放autofill保护值，后台tab物理点击无效
- ⭐**一键释放与登录**：利用顶层 `await`，在单次 `web_execute_js` 中连贯完成：
  1. CDP batch发送 `Page.bringToFront` 切到前台。
  2. JS获取输入框坐标。
  3. CDP发送 `Input.dispatchMouseEvent` (mousePressed) 物理点击释放autofill。
  4. `await new Promise(r => setTimeout(r, 500))` 等待释放。
  5. 派发 `input`/`change` 事件唤醒前端框架（解禁登录按钮）。
  6. 触发登录点击。
- ⚠只需 `mousePressed`，无需 `mouseReleased`。点击一个字段即释放全页。
- ⚠使用await时需显式`return`返回值，否则async包裹层默认返回null。

## 验证码/页面视觉截图
- ⭐首选CDP截图：`Page.captureScreenshot`(format:'png')→返回base64，无需前台/后台tab也行，全页高清
- 验证码canvas/img：JS `canvas.toDataURL()` 直接拿base64最干净
- 备选：`window.open(location.href,'_blank')` 前台开新标签→win32截图→完后close

## 直接import(仅作调试使用)
- `sys.path.insert(0, GenericAgent根目录)`, `from TMWebDriver import TMWebDriver`
- `d=TMWebDriver()`, `d.set_session('url_pattern')`, `d.execute_js('code')` → 返回`{'data': value}`(非裸值)
- 配合simphtml：`str(simphtml.optimize_html_for_tokens(html))` → 注意返回BS4 Tag需str()

## 跨域iframe操控(postMessage中继)
- 跨域iframe的contentDocument不可访问，web_execute_js只在顶层执行
- 扩展content script已支持：iframe内不return，改为监听postMessage并eval执行+回传结果
- 顶层发送：`iframe.contentWindow.postMessage({type:'ljq_exec', id, code}, '*')`
- iframe回传：`{type:'ljq_result', id, result}` 通过window.addEventListener('message')接收
- ⚠只能eval表达式，不支持return/函数体包装，构造代码时注意
- 流程：发postMessage→等→读window._ljqResults[id]获取结果
- 已验证：读取iframe内DOM(document.title)、填写input均成功

## 连不上排查
web_scan失败时按序排查：
①扩展没装？→检查Chrome扩展列表(chrome://extensions)是否有TMWebDriver扩展
  没找到→走web_setup_sop；找到→确认已启用
②浏览器没开？→检查①对应的浏览器进程是否在跑(tasklist/ps)，没有则启动并打开正常URL（⚠about:blank等内部页不加载扩展）
③WS后台挂了？→socket.connect_ex(('127.0.0.1',18766))非0即dead→手动`from TMWebDriver import TMWebDriver; TMWebDriver()`起master

## 性能
- ⚠ URL必须用`127.0.0.1`不用`localhost`。Windows下localhost先尝试IPv6(::1)超时2s再回退IPv4，每次HTTP请求多2s