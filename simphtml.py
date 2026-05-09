try: from bs4 import BeautifulSoup
except ImportError: print("[Error] BeautifulSoup4 未安装，请叫Agent安装BeautifulSoup4，再使用web相关工具。")

js_optHTML = r'''function optHTML(text_only=false) {
function createEnhancedDOMCopy() {  
  const nodeInfo = new WeakMap();  
  const ignoreTags = ['SCRIPT', 'STYLE', 'NOSCRIPT', 'META', 'LINK', 'COLGROUP', 'COL', 'TEMPLATE', 'PARAM', 'SOURCE'];  
  const ignoreIds = ['ljq-ind'];  
  function cloneNode(sourceNode, keep=false) {  
    if (sourceNode.nodeType === 8 ||   
        (sourceNode.nodeType === 1 && (  
          ignoreTags.includes(sourceNode.tagName) ||   
          (sourceNode.id && ignoreIds.includes(sourceNode.id))  
        ))) {  
      return null;  
    }  
    if (sourceNode.nodeType === 3) return sourceNode.cloneNode(false);  
    const clone = sourceNode.cloneNode(false);
    if ((sourceNode.tagName === 'INPUT' || sourceNode.tagName === 'TEXTAREA') && sourceNode.value) clone.setAttribute('value', sourceNode.value);
    if (sourceNode.tagName === 'INPUT' && (sourceNode.type === 'radio' || sourceNode.type === 'checkbox') && sourceNode.checked) clone.setAttribute('checked', '');
    else if (sourceNode.tagName === 'SELECT' && sourceNode.value) clone.setAttribute('data-selected', sourceNode.value);  
    try { if (sourceNode.matches && sourceNode.matches(':-webkit-autofill')) { clone.setAttribute('data-autofilled', 'true'); if (!sourceNode.value) clone.setAttribute('value', '⚠️受保护-读tmwebdriver_sop的autofill章节提取'); } } catch(e) {}

    const isDropdown = sourceNode.classList?.contains('dropdown-menu') ||   
             /dropdown|menu/i.test(sourceNode.className) || sourceNode.getAttribute('role') === 'menu'; 
    const _ddItems = isDropdown ? sourceNode.querySelectorAll('a, button, [role="menuitem"], li').length : 0;
    const isSmallDropdown = _ddItems > 0 && _ddItems <= 7 && sourceNode.textContent.length < 500;  

    const childNodes = [];  
    for (const child of sourceNode.childNodes) {  
      const childClone = cloneNode(child, keep || isSmallDropdown);  
      if (childClone) childNodes.push(childClone);  
    }  
    if (sourceNode.tagName === 'IFRAME') {
      try {
        const iDoc = sourceNode.contentDocument || sourceNode.contentWindow?.document;
        if (iDoc && iDoc.body && iDoc.body.children.length > 0) {
          const wrapper = document.createElement('div');
          wrapper.setAttribute('data-iframe-content', sourceNode.src || '');
          for (const ch of iDoc.body.childNodes) {
            const c = cloneNode(ch, keep);
            if (c) wrapper.appendChild(c);
          }
          if (wrapper.childNodes.length) childNodes.push(wrapper);
        }
      } catch(e) {}
    }
    if (sourceNode.shadowRoot) {
      for (const shadowChild of sourceNode.shadowRoot.childNodes) {
        const shadowClone = cloneNode(shadowChild, keep);
        if (shadowClone) childNodes.push(shadowClone);
      }
    }

    const rect = sourceNode.getBoundingClientRect();
    const style = window.getComputedStyle(sourceNode);
    const area = (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) <= 0)?0:rect.width * rect.height;
    const isVisible = (rect.width > 1 && rect.height > 1 &&   
                  style.display !== 'none' && style.visibility !== 'hidden' &&   
                  parseFloat(style.opacity) > 0 &&  
                  Math.abs(rect.left) < 5000 && Math.abs(rect.top) < 5000) 
                  || isSmallDropdown;  
    const zIndex = style.position !== 'static' ? (parseInt(style.zIndex) || 0) : 0;
  
    let info = {
          rect, area, isVisible, isSmallDropdown, zIndex,
          style: {  
            display: style.display, visibility: style.visibility,  
            opacity: style.opacity, position: style.position
          }};
    
    const nonTextChildren = childNodes.filter(child => child.nodeType !== 3);  
    const hasValidChildren = nonTextChildren.length > 0;  
          
    if (hasValidChildren) {
      const childrenInfos = nonTextChildren.map(c => nodeInfo.get(c)).filter(i => i && i.rect && i.rect.width > 0 && i.rect.height > 0);
      const bgAlpha = (() => {
        const c = style.backgroundColor;
        if (!c || c === 'transparent') return 0;
        const m = c.match(/rgba?\([^)]+,\s*([\d.]+)\)/);
        return m ? parseFloat(m[1]) : 1;
      })();
      const hasVisualBg = bgAlpha > 0.1 || style.backgroundImage !== 'none' || (style.backdropFilter && style.backdropFilter !== 'none') || style.boxShadow !== 'none';
      
      if (!hasVisualBg && childrenInfos.length > 0) {
        // Skip fixed/absolute children when computing parent's merged rect (they're out of flow)
        const flowChildren = childrenInfos.filter(cInfo => cInfo.style && cInfo.style.position !== 'fixed' && cInfo.style.position !== 'absolute');
        if (flowChildren.length > 0) {
          let minL = Infinity, minT = Infinity, maxR = -Infinity, maxB = -Infinity;
          for (const cInfo of flowChildren) {
            minL = Math.min(minL, cInfo.rect.left);
            minT = Math.min(minT, cInfo.rect.top);
            maxR = Math.max(maxR, cInfo.rect.right);
            maxB = Math.max(maxB, cInfo.rect.bottom);
          }
          info.rect = { left: minL, top: minT, right: maxR, bottom: maxB, width: maxR - minL, height: maxB - minT };
          info.area = info.rect.width * info.rect.height;
        } else {
          const maxC = childrenInfos.filter(i => i.isVisible).sort((a, b) => b.area - a.area)[0];
          if (maxC && maxC.area > 10000 && (!isVisible || maxC.area > info.area * 5)) info = maxC;
        }
      }
    }

    if (sourceNode.nodeType === 1 && sourceNode.tagName === 'DIV') {    
      if (!hasValidChildren && !sourceNode.textContent.trim()) return null; 
    }  
    // aria-hidden + not visible = truly hidden (e.g. mobile menus), remove even if has children
    if (sourceNode.getAttribute && sourceNode.getAttribute('aria-hidden') === 'true' && !info.isVisible) {
      return null;
    }
    if (info.isVisible || hasValidChildren || keep) {  
      childNodes.forEach(child => clone.appendChild(child));  
      return clone;  
    }  
    return null;  
  }  
  
  return {  
    domCopy: cloneNode(document.body),  
    getNodeInfo: node => nodeInfo.get(node),  
    isVisible: node => {  
      const info = nodeInfo.get(node);  
      return info && info.isVisible;  
    }  
  };  
}  
const { domCopy, getNodeInfo, isVisible } = createEnhancedDOMCopy();
if (text_only) {
  const blocks = new Set(['DIV','P','H1','H2','H3','H4','H5','H6','LI','TR','SECTION','ARTICLE','HEADER','FOOTER','NAV','BLOCKQUOTE','PRE','HR','BR','DT','DD','FIGCAPTION','DETAILS','SUMMARY']);
  domCopy.querySelectorAll('*').forEach(el => {
    if (blocks.has(el.tagName)) el.insertAdjacentText('beforebegin', '\n');
  });
  domCopy.querySelectorAll('input:not([type=hidden]),textarea,select').forEach(el=>{
    const p=[el.tagName,el.id&&'#'+el.id,el.getAttribute('name')&&'name='+el.getAttribute('name'),el.tagName==='INPUT'&&'type='+(el.getAttribute('type')||'text'),el.getAttribute('placeholder')&&'"'+el.getAttribute('placeholder')+'"',el.getAttribute('data-autofilled')&&'autofilled',el.disabled&&'disabled',el.tagName==='SELECT'&&el.getAttribute('data-selected')&&'="'+el.getAttribute('data-selected')+'"'].filter(Boolean).join(' ');
    el.insertAdjacentText('beforebegin','\n['+p+']\n');
  });
  domCopy.querySelectorAll('button[disabled]').forEach(el=>el.insertAdjacentText('beforebegin','[DISABLED] '));
  return domCopy.textContent;
}
const viewportArea = window.innerWidth * window.innerHeight; 

function analyzeNode(node, pPathType='main') {  
    // 处理非元素节点和叶节点  
    if (node.nodeType !== 1 || !node.children.length) {  
      node.nodeType === 1 && (node.dataset.mark = 'K:leaf');  
      return;  
    }  
    const pathType = (node.dataset.mark === 'K:secondary') ? 'second' : pPathType;  
    const nodeInfoData = getNodeInfo(node);
    if (!nodeInfoData || !nodeInfoData.rect) return;
    const rectn = nodeInfoData.rect; 
    if (rectn.width < window.innerWidth * 0.8 && rectn.height < window.innerHeight * 0.8) return node;
    if (node.tagName === 'TABLE') return;
    const children = Array.from(node.children);  
    if (children.length === 1) {  
      node.dataset.mark = 'K:container';  
      return analyzeNode(children[0], pathType);  
    }  
    if (children.length > 10) return;
    
    // 获取子元素信息并排序  
    const childrenInfo = children.map(child => {  
      const info = getNodeInfo(child) || { rect: {}, style: {} };  
      return { node: child, rect: info.rect, style: info.style, 
          area: info.area, zIndex: (info.zIndex || 0), isVisible: info.isVisible };  
    });
    childrenInfo.sort((a, b) => b.area - a.area);  
    
    // 检测是划分还是覆盖  
    const isOverlay = hasOverlap(childrenInfo);  
    node.dataset.mark = isOverlay ? 'K:overlayParent' : 'K:partitionParent';  
    
    if (isOverlay) handleOverlayContainer(childrenInfo, pathType);  
    else handlePartitionContainer(childrenInfo, pathType);  

    console.log(`${isOverlay ? '覆盖' : '划分'}容器:`, node, `子元素数量: ${children.length}`);  
    console.log('子元素及标记:', children.map(child => ({   
      element: child,   
      mark: child.dataset.mark || '无',  
      info: getNodeInfo ? getNodeInfo(child) : undefined  
    })));  
    for (const child of children)  
      if (!child.dataset.mark || child.dataset.mark[0] !== 'R') analyzeNode(child, pathType);  
  }  
  
  // 处理划分容器  
  function handlePartitionContainer(childrenInfo, pathType) {  
    childrenInfo.sort((a, b) => b.area - a.area);
    const totalArea = childrenInfo.reduce((sum, item) => sum + item.area, 0);  
    console.log(childrenInfo[0].area / totalArea);
    const hasMainElement = childrenInfo.length >= 1 &&   
                          (childrenInfo[0].area / totalArea > 0.5) &&   
                          (childrenInfo.length === 1 || childrenInfo[0].area > childrenInfo[1].area * 2);  
    if (hasMainElement) {  
      childrenInfo[0].node.dataset.mark = 'K:main';
      for (let i = 1; i < childrenInfo.length; i++) {  
        const child = childrenInfo[i];  
        let className = (child.node.getAttribute('class') || '').toLowerCase();
        let isSecondary = containsButton(child.node);
        if (className.includes('nav')) isSecondary = true;
        if (className.includes('breadcrumbs')) isSecondary = true;
        if (className.includes('header') && className.includes('table')) isSecondary = true;
        if (child.node.innerHTML.trim().replace(/\s+/g, '').length < 500) isSecondary = true;
        if (child.node.textContent.trim().length > 200) isSecondary = true;  // P3: 有实质文本内容则保留
        if (child.style.visibility === 'hidden') isSecondary = false;
        if (isSecondary) child.node.dataset.mark = 'K:secondary';  
        else child.node.dataset.mark = 'K:nonEssential';  
      }  
    } else {  
      return; // relaxed: skip equalmany filtering, list truncation handles token budget
      const uniqueClassNames = new Set(childrenInfo.map(item => item.node.getAttribute('class') || '')).size;  
      const highClassNameVariety = uniqueClassNames >= childrenInfo.length * 0.8;  
      if (pathType !== 'main' && highClassNameVariety && childrenInfo.length > 5) {
        childrenInfo.forEach(child => child.node.dataset.mark = 'R:equalmany');  
      } else {
        childrenInfo.forEach(child => child.node.dataset.mark = 'K:equal');  
      }
    }  
  }  

  function containsButton(container) {  
    const hasStandardButton = container.querySelector('button, input[type="button"], input[type="submit"], [role="button"]') !== null;  
    if (hasStandardButton) return true;  
    const hasClassButton = container.querySelector('[class*="-btn"], [class*="-button"], .button, .btn, [class*="btn-"]') !== null;  
    return hasClassButton;  
  }   
  
  function handleOverlayContainer(childrenInfo, pathType) {  
    // elementFromPoint ground truth: 让浏览器告诉我们谁在视觉最上层
    const _efp = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
    if (_efp) { let _el = _efp; while (_el) { const _h = childrenInfo.find(c => c.node.id && c.node.id === _el.id); if (_h) { _h.zIndex = 9999; break; } _el = _el.parentElement; } }
    const sorted = [...childrenInfo].sort((a, b) => b.zIndex - a.zIndex);  
    console.log('排序后的子元素:', sorted);
    if (sorted.length === 0) return;  
    
    const top = sorted[0];  
    const rect = top.rect;  
    const topNode = top.node; 
    const isComplex = top.node.querySelectorAll('input, select, textarea, button, a, [role="button"]').length >= 1;  

    const textContent = topNode.textContent?.trim() || '';  
    const textLength = textContent.length;  
    const hasLinks = topNode.querySelectorAll('a').length > 0;  
    const isMostlyText = textLength > 7 && !hasLinks;  

    const centerDiff = Math.abs((rect.left + rect.width/2) - window.innerWidth/2) / window.innerWidth;  
    const minDimensionRatio = Math.min(rect.width / window.innerWidth, rect.height / window.innerHeight);  
    const maxDimensionRatio = Math.max(rect.width / window.innerWidth, rect.height / window.innerHeight);  
    const isNearTop = rect.top < 50;  
    const isDialog = (top.node.querySelector('iframe') || top.node.querySelector('button') || top.node.querySelector('input')) && centerDiff < 0.3;

    if (isComplex && centerDiff < 0.2 && 
        ((minDimensionRatio > 0.2 && rect.width/window.innerWidth < 0.98) || minDimensionRatio > 0.95)) {  
      top.node.dataset.mark = 'K:mainInteractive';  
       sorted.slice(1).forEach(e => {
          if ((parseInt(e.zIndex)||0) <= (parseInt(sorted[0].zIndex)||0)) {
              e.node.dataset.mark = 'R:covered';
          } else {
              e.node.dataset.mark = 'K:noncovered';
          }
      });
    } else {
      if (isComplex && isNearTop && maxDimensionRatio > 0.4 && top.isVisible) {
        top.node.dataset.mark = 'K:topBar';
      } else if (isMostlyText || isComplex || isDialog) {  
        topNode.dataset.mark = 'K:messageContent'; 
      } else {  
        topNode.dataset.mark = 'R:floatingAd'; 
      }  
      const rest = sorted.slice(1);  
      rest.length && (!hasOverlap(rest) ? handlePartitionContainer(rest, pathType) : handleOverlayContainer(rest, pathType));  
    } 
  }  
    
  function hasOverlap(items) {  
    return items.some((a, i) =>   
      items.slice(i+1).some(b => {  
        const r1 = a.rect, r2 = b.rect;  
        if (!r1.width || !r2.width || !r1.height || !r2.height) {return false;}
        const epsilon = 1;
        const x1 = r1.x !== undefined ? r1.x : r1.left;
        const y1 = r1.y !== undefined ? r1.y : r1.top;
        const x2 = r2.x !== undefined ? r2.x : r2.left;
        const y2 = r2.y !== undefined ? r2.y : r2.top;
        return !(x1 + r1.width <= x2 + epsilon || x1 >= x2 + r2.width - epsilon || 
            y1 + r1.height <= y2 + epsilon || y1 >= y2 + r2.height - epsilon
        );
      })
    );  
}

// Hoist top 1-2 deep fixed dialogs to body level for overlay detection
const _fc = [...domCopy.querySelectorAll('*')].filter(el => {
  if (el.parentNode === domCopy) return false;
  const info = getNodeInfo(el);
  if (!info?.rect || info.style.position !== 'fixed') return false;
  const r = info.rect, cover = (r.width * r.height) / viewportArea;
  const cd = Math.abs((r.left + r.width/2) - window.innerWidth/2) / window.innerWidth;
  return cover > 0.15 && cover < 1.0 && cd < 0.3 && el.querySelector('button, input, a, [role="button"], iframe');
}).filter((el, _, arr) => !arr.some(o => o !== el && o.contains(el)))
  .sort((a, b) => (getNodeInfo(b).rect.width * getNodeInfo(b).rect.height) - (getNodeInfo(a).rect.width * getNodeInfo(a).rect.height))
  .slice(0, 2);
_fc.forEach(el => { const r = getNodeInfo(el).rect; console.log('[simphtml] Hoisted fixed dialog:', el.tagName + (el.id ? '#'+el.id : '') + (el.className ? '.'+String(el.className).split(' ')[0] : ''), Math.round(r.width)+'x'+Math.round(r.height), Math.round(100*r.width*r.height/viewportArea)+'%'); el.parentNode.removeChild(el); domCopy.appendChild(el); });
const result = analyzeNode(domCopy); 
domCopy.querySelectorAll('[data-mark^="R:"]').forEach(el=>el.parentNode?.removeChild(el));  
let root = domCopy;  
while (root.children.length === 1) {  
  root = root.children[0];  
}  
for (let ii = 0; ii < 3; ii++) {
  root.querySelectorAll('div').forEach(div => (!div.textContent.trim() && div.children.length === 0) && div.remove());
}
root.querySelectorAll('[data-mark]').forEach(e => e.removeAttribute('data-mark'));  
root.removeAttribute('data-mark');
root.querySelectorAll('iframe').forEach(f => {
  if (f.children.length) {
    const d = document.createElement('div');
    for (const a of f.attributes) d.setAttribute(a.name, a.value);
    d.setAttribute('data-tag', 'iframe');
    while (f.firstChild) d.appendChild(f.firstChild);
    f.parentNode.replaceChild(d, f);
  }
});
return root.outerHTML;
    }
optHTML()'''

js_findMainList = r'''function findMainList(startElement = null) {
        const root = startElement || document.body;
        const MIN_CHILDREN = 8;
        const MAX_CONTAINERS = 20;

        // 全局扫描：收集候选容器，按 l1 + l2*0.1 排序（l2=孙子元素数，捕获表格等多层结构）
        const candidates = [];
        const allEls = root.querySelectorAll('*');
        for (const node of allEls) {
            if (node.closest('svg')) continue;
            const l1 = node.children.length;
            if (l1 < 5) continue;
            let l2 = 0;
            for (const child of node.children) l2 += child.children.length;
            const score = l1 + l2 * 0.1;
            if (score >= MIN_CHILDREN) candidates.push({node, score});
        }
        candidates.sort((a, b) => b.score - a.score);
        const toProcess = candidates.slice(0, MAX_CONTAINERS).map(c => c.node);

        // 对每个容器找候选组并评分
        let allCandidates = [];
        for (const container of toProcess) {
            const topGroups = findTopGroups(container, 3);
            for (const groupInfo of topGroups) {
                const items = findMatchingElements(container, groupInfo.selector);
                if (items.length >= 5) {
                    const score = scoreContainer(container, items) + groupInfo.score;
                    if (score >= 30) {
                        allCandidates.push({ container, selector: groupInfo.selector, items, score });
                    }
                }
            }
        }

        // 按分数降序排列
        allCandidates.sort((a, b) => b.score - a.score);

        // 去重：移除与更高分候选重叠超50%的结果
        const kept = [];
        for (const cand of allCandidates) {
            let dominated = false;
            for (const k of kept) {
                if (k.container.contains(cand.container) || cand.container.contains(k.container)) {
                    const kSet = new Set(k.items);
                    const overlap = cand.items.filter(it => kSet.has(it)).length;
                    if (overlap > cand.items.length * 0.5) { dominated = true; break; }
                }
            }
            if (!dominated) kept.push(cand);
        }

        function describeResult(container, items, selector, score) {
            if(container&&!container.id)container.id='_ljq'+(window._lci=(window._lci||0)+1);
            const cTag = container ? container.tagName : null;
            const cId = container ? (container.id || '') : '';
            const cClass = container ? (String(container.className || '').trim()) : '';
            const result = {
                containerTag: cTag, containerId: cId, containerClass: cClass,
                itemCount: items.length,
            };
            let prefix = '';
            if (cId) prefix = '#' + CSS.escape(cId);
            if (selector) result.selector = prefix ? (prefix + ' > ' + selector) : selector;
            if (score !== undefined) result.score = score;
            if (items.length > 0) {
                result.firstItemPreview = items[0].outerHTML.substring(0, 200);
                result.itemTags = items.slice(0, 10).map(el => el.tagName + (el.className ? '.' + String(el.className).trim().split(/\s+/)[0] : ''));
            }
            return result;
        }

        if (kept.length === 0) return [];

        return kept.map(c => describeResult(c.container, c.items, c.selector, c.score));
    }
    
    function findTopGroups(container, limit) {
        const children = Array.from(container.children).filter(c => !c.closest('svg'));
        const totalChildren = children.length;
        if (totalChildren < 3) return [];

        const minGroupSize = Math.max(3, Math.floor(totalChildren * 0.2));
        const groups = [];

        // 统计标签和类名
        const tagFreq = {}, classFreq = {}, tagMap = {}, classMap = {};

        children.forEach(child => {
            // 统计标签
            const tag = child.tagName.toLowerCase();
            if (tag === "td") return;
            tagFreq[tag] = (tagFreq[tag] || 0) + 1;
            if (!tagMap[tag]) tagMap[tag] = [];
            tagMap[tag].push(child);

            // 统计类名
            if (child.className) {
                child.className.trim().split(/\s+/).forEach(cls => {
                    if (cls) {
                        classFreq[cls] = (classFreq[cls] || 0) + 1;
                        if (!classMap[cls]) classMap[cls] = [];
                        classMap[cls].push(child);
                    }
                });
            }
        });

        // 评分函数
        const scoreGroup = (selector, elements) => {
            const coverage = elements.length / totalChildren;
            let specificity = selector.startsWith('.')
            ? (0.6 + (selector.match(/\./g).length - 1) * 0.1) // 类选择器
            : (selector.includes('.')
               ? (0.7 + (selector.match(/\./g).length) * 0.1) // 标签+类
               : 0.3); // 纯标签
            return (coverage * 0.5) + (specificity * 0.5);
        };

        // 添加标签组
        Object.keys(tagFreq).forEach(tag => {
            if (tag !== "div" && tagFreq[tag] >= minGroupSize) {
                groups.push({
                    selector: tag,
                    elements: tagMap[tag],
                    score: scoreGroup(tag, tagMap[tag]) - 0.5
                });
            }
        });

        // 添加类组
        Object.keys(classFreq).forEach(cls => {
            if (classFreq[cls] >= minGroupSize) {
                const selector = '.' + CSS.escape(cls);
                groups.push({
                    selector,
                    elements: classMap[cls],
                    score: scoreGroup(selector, classMap[cls])
                });
            }
        });
        // 添加标签+类组合
        const topTags = Object.keys(tagFreq).filter(t => tagFreq[t] >= minGroupSize).slice(0, 3);
        const topClasses = Object.keys(classFreq).filter(c => classFreq[c] >= minGroupSize).sort((a, b) => classFreq[b] - classFreq[a]).slice(0, 3);

        // 标签+类
        topTags.forEach(tag => {
            topClasses.forEach(cls => {
                const elements = children.filter(el =>
                                                 el.tagName.toLowerCase() === tag &&
                                                 el.className && el.className.split(/\s+/).includes(cls)
                                                );

                if (elements.length >= minGroupSize) {
                    const selector = tag + '.' + CSS.escape(cls);
                    groups.push({selector, elements, score: scoreGroup(selector, elements)});
                }
            });
        });

        // 多类组合
        for (let i = 0; i < topClasses.length; i++) {
            for (let j = i + 1; j < topClasses.length; j++) {
                const elements = children.filter(el =>
                                                 el.className && el.className.split(/\s+/).includes(topClasses[i]) && el.className.split(/\s+/).includes(topClasses[j]));

                if (elements.length >= minGroupSize) {
                    const selector = '.' + CSS.escape(topClasses[i]) + '.' + CSS.escape(topClasses[j]);
                    groups.push({selector, elements,score: scoreGroup(selector, elements)});
                }
            }
        }
        // 返回得分最高的N个组
        return groups.sort((a, b) => b.score - a.score).slice(0, limit);
    }

    function findMatchingElements(container, selector) {
        try {
            return Array.from(container.querySelectorAll(selector));
        } catch (e) {
            // 处理无效选择器
            console.error('Invalid selector:', selector, e);
            return [];
        }
    }

    function scoreContainer(container, items) {
        if (!container || items.length < 3) return 0;
        // 1. 计算基础面积数据
        const containerRect = container.getBoundingClientRect();
        const containerArea = containerRect.width * containerRect.height;
        if (containerArea < 10000) return 0; // 容器太小

        // 收集列表项面积数据
        const itemAreas = [];
        let totalItemArea = 0;
        let visibleItems = 0;

        items.forEach(item => {
            const rect = item.getBoundingClientRect();
            const area = rect.width * rect.height;
            if (area > 0) {
                totalItemArea += area;
                itemAreas.push(area);
                visibleItems++;
            }
        });
        // 如果可见项太少，返回低分
        if (visibleItems < 3) return 0;
        // 防止异常值：确保面积不超过容器
        totalItemArea = Math.min(totalItemArea, containerArea * 0.98);
        const areaRatio = totalItemArea / containerArea;
        // 3. 计算各项评分 - 使用线性插值而非阶梯
        // 3.2 面积比评分 - 最多40分，连续曲线
        // 使用sigmoid函数让评分更平滑
        const areaScore = 40 / (1 + Math.exp(-12 * (areaRatio - 0.4)));

        // 3.3 均匀性评分 - 最多20分，连续曲线
        let uniformityScore = 0;
        if (itemAreas.length >= 3) {
            const mean = itemAreas.reduce((sum, area) => sum + area, 0) / itemAreas.length;
            const variance = itemAreas.reduce((sum, area) => sum + Math.pow(area - mean, 2), 0) / itemAreas.length;
            const cv = mean > 0 ? Math.sqrt(variance) / mean : 1;
            // 指数衰减函数，cv越小分数越高
            uniformityScore = 20 * Math.exp(-2.5 * cv);
        }

        const baseScore = Math.log2(visibleItems) * 5 + Math.floor(visibleItems / 5) * 0.25;
        const rawCountScore = Math.min(40, baseScore);
        const countScore = rawCountScore * Math.max(0.1, uniformityScore / 20);

        // 3.4 容器尺寸评分 - 最多15分，连续曲线
        const viewportArea = window.innerWidth * window.innerHeight;
        const containerViewportRatio = containerArea / viewportArea;
        const sizeScore = 2 * (1 - 1/(1 + Math.exp(-10 * (containerViewportRatio - 0.25))));  

        let layoutScore = 0;
        if (items.length >= 3) {
            // 坐标分组并计算行列数
            const uniqueRows = new Set(items.map(item => Math.round(item.getBoundingClientRect().top / 5) * 5)).size;
            const uniqueCols = new Set(items.map(item => Math.round(item.getBoundingClientRect().left / 5) * 5)).size;
            // 如果是单行或单列，直接给满分；否则评估网格质量
            if (uniqueRows === 1 || uniqueCols === 1) { layoutScore = 20;
            } else {
                const coverage = Math.min(1, items.length / (uniqueRows * uniqueCols));
                const efficiency = Math.max(0, 1 - (uniqueRows + uniqueCols) / (2 * items.length));
                layoutScore = 20 * (0.7 * coverage + 0.3 * efficiency);
            }
        }

        // 总分 - 仍然保持100分左右的总分
        const totalScore = countScore + areaScore + uniformityScore + layoutScore + sizeScore;

        if (totalScore > 100)
            console.log(container, {
                total: totalScore.toFixed(2),
                count: countScore.toFixed(2),
                areaRatio: areaRatio.toFixed(2),
                area: areaScore.toFixed(2),
                uniformity: uniformityScore.toFixed(2),
                size: sizeScore.toFixed(2),
                layout: layoutScore.toFixed(2)
            });

        return totalScore;
    }'''

def optimize_html_for_tokens(html):  
    if type(html) is str: soup = BeautifulSoup(html, 'html.parser')  
    else: soup = html
    for svg in soup.find_all('svg'):
        svg.clear(); svg.attrs = {}
    [tag.attrs.pop('style', None) for tag in soup.find_all(True)]  
    for tag in soup.find_all(True):  
        if tag.has_attr('src'):  
            if tag['src'].startswith('data:'): tag['src'] = '__img__'  
            elif len(tag['src']) > 30: tag['src'] = '__url__'  
        if tag.has_attr('href') and len(tag['href']) > 30: tag['href'] = '__link__'  
        if tag.has_attr('action') and len(tag['action']) > 30: tag['action'] = '__url__'
        for a in ('value', 'title', 'alt'):
            if tag.has_attr(a) and isinstance(tag[a], str) and len(tag[a]) > 100: tag[a] = tag[a][:50] + ' ...'
        for attr in list(tag.attrs.keys()):  
            if attr not in ['id', 'class', 'name', 'src', 'href', 'alt', 'value', 'type', 'placeholder',
                          'disabled', 'checked', 'selected', 'readonly', 'required', 'multiple',
                          'role', 'aria-label', 'aria-expanded', 'aria-hidden', 'contenteditable',
                          'title', 'for', 'action', 'method', 'target', 'colspan', 'rowspan']:  
                if attr.startswith('data-v'): tag.attrs.pop(attr, None)
                elif attr.startswith('data-') and isinstance(tag[attr], str) and len(tag[attr]) > 20:  
                    tag[attr] = '__data__'  
                elif not attr.startswith('data-'): tag.attrs.pop(attr, None)  
    return soup


temp_monitor_js = """function startStrMonitor(interval) {  
        if (window._tm && window._tm.id) clearInterval(window._tm.id);  
        window._tm = {extract: () => {  
            const texts = new Set(), walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);  
            let node, t, s; while (node = walker.nextNode())   
                ((t = node.textContent.trim()) && t.length > 10 && !(s = t.substring(0, 20)).includes('_')) && texts.add(s);  
            return texts;  
        }}; 
        window._tm.init = window._tm.extract();  
        window._tm.all = new Set();  
        window._tm.id = setInterval(() => window._tm.extract().forEach(t => window._tm.all.add(t)), interval);  
    }  
    startStrMonitor(450);  
"""  
def start_temp_monitor(driver):  
    try: driver.execute_js(temp_monitor_js)
    except: pass

def get_temp_texts(driver):  
    js = """function stopStrMonitor() {  
        if (!window._tm) return [];  
        clearInterval(window._tm.id);  
        const final = window._tm.extract();  
        const newlySeen = [...window._tm.all].filter(t => !window._tm.init.has(t));
        let result;
        if (newlySeen.length < 8) {
            result = newlySeen;
        } else {
            result = newlySeen.filter(t => !final.has(t));
        }
        delete window._tm;  
        return result;  
        }  
        stopStrMonitor();  
    """  
    try: return list(set(driver.execute_js(js).get('data', [])))
    except Exception as e: 
        print(e)
        return []
    
import time, re, os
def get_main_block(driver, extra_js="", text_only=False): 
    page = driver.execute_js(f"{extra_js}\n{js_optHTML}\nreturn optHTML({str(text_only).lower()});").get('data', '')
    if text_only:
        page = re.sub(r' {2,}', ' ', page)           # 连续空格→单空格
        page = re.sub(r'^ +', '', page, flags=re.M)   # 去行首空格
        page = re.sub(r'(\n\s*){3,}', '\n\n', page)   # 3+空行→1空行
        return page.strip()
    return page

def find_changed_elements(before_html, after_html):
    before_soup = BeautifulSoup(before_html, 'html.parser')
    after_soup = BeautifulSoup(after_html, 'html.parser')
    def direct_text(el):
        return ''.join(t.strip() for t in el.find_all(string=True, recursive=False)).strip()
    def get_sig(el):
        attrs = {k:v for k,v in el.attrs.items() if k != 'data-track-id'}
        return f"{el.name}:{attrs}:{direct_text(el)}"
    def build_sigs(soup):
        result = {}
        for el in soup.find_all(True):
            sig = get_sig(el)
            result.setdefault(sig, []).append(el)
        return result
    before_sigs, after_sigs = build_sigs(before_soup), build_sigs(after_soup)
    changed = []
    for sig, els in after_sigs.items():
        if sig not in before_sigs: changed.extend(els)
        elif len(els) > len(before_sigs[sig]): changed.extend(els[:len(els) - len(before_sigs[sig])])
    if len(changed) == 0 and str(before_soup) != str(after_soup):
        before_els, after_els = before_soup.find_all(True), after_soup.find_all(True)
        for i in range(min(len(before_els), len(after_els))):
            if get_sig(before_els[i]) != get_sig(after_els[i]): changed.append(after_els[i])
    # 变化边界: parent不在changed中的元素
    cids = set(id(el) for el in changed)
    boundaries = [el for el in changed if el.parent is None or id(el.parent) not in cids]
    top = max(boundaries, key=lambda el: len(str(el))) if boundaries else None
    result = {"changed": len(changed)}
    if top:
        h = str(top)
        result["top_change"] = h if len(h) <= 2000 else h[:2000] + '...[TRUNCATED]'
    return result

def get_html(driver, cutlist=False, maxchars=35000, instruction="", extra_js="", text_only=False):
    if cutlist: rr = driver.execute_js(js_findMainList + "return findMainList(document.body);").get('data', [])
    page = get_main_block(driver, extra_js=extra_js, text_only=text_only)
    if text_only: return page
    soup = optimize_html_for_tokens(page)
    for div in soup.select('div[data-tag="iframe"]'):
        div.name = 'iframe'; del div['data-tag']
    html = str(soup)
    if not cutlist: return html
    lists = rr if isinstance(rr, list) else ([rr] if isinstance(rr, dict) and rr.get('selector') else [])
    if lists: print(f"[cutlist] Found {len(lists)} list(s): {[e.get('selector','?') if isinstance(e,dict) else '?' for e in lists]}")
    for entry in lists:
        sel = entry.get('selector') if isinstance(entry, dict) else None
        if not sel: continue
        try: items = soup.select(sel)
        except Exception: print(f'[cutlist] skip invalid selector: {sel}'); continue
        if len(items) < 5: continue
        total_len = sum(len(str(it)) for it in items)
        avg_len = total_len / len(items)
        print(f"[cutlist]   '{sel}': {len(items)} items, avg {avg_len:.0f} chars, total {total_len}, if keep 3, save ~{total_len - 3 * avg_len:.0f} chars")
        if avg_len < 200 or (avg_len < 700 and total_len < 2500): continue
        hit = [it for it in items if instruction and instruction.strip() and instruction in it.get_text(" ",strip=True)]
        keep = hit[:6] if hit else items[:3]
        removed = [it for it in items if it not in keep]
        sample_texts = []
        for rm in removed[:5]:
            txt = rm.get_text(" ", strip=True)[:40]
            if txt: sample_texts.append(txt)
        hint_parts = [f'[FAKE ELEMENT] {len(removed)} more items hidden, selector: "{sel}"']
        if sample_texts: hint_parts.append('Hidden items: ' + ','.join(f'"{t}"' for t in sample_texts))
        hint_tag = soup.new_tag("div")
        hint_tag.string = ' '.join(hint_parts)
        if keep: keep[-1].insert_after(hint_tag)
        for it in removed: it.decompose()
    ss = str(optimize_html_for_tokens(soup)) if lists else html
    print(f"[get_html] Result: {len(html)} -> {len(ss)} chars after cutlist ({100-len(ss)*100//len(html)}% saved)")
    if len(ss) > maxchars: ss = str(smart_truncate(soup, maxchars))
    return ss

def smart_truncate(soup, budget, _depth=0):
    """原地截断 soup 使其接近 budget 字符。
    策略：穿透单子元素找分叉点；top3 能扛住 over 则按比例分担，否则从尾部删子元素。"""
    CUT_THRESHOLD = 8000  # 小于此值直接去尾，大于则继续递归找分叉点
    indent = '  ' * _depth
    def cut(ele, keep):
        from bs4 import NavigableString
        s = str(ele)
        over = len(s) - keep
        if over <= 0: return
        # 保护 FAKE ELEMENT 提示标签
        protected = [c.extract() for c in ele.find_all(lambda tag: tag.string and '[FAKE ELEMENT]' in tag.string)]
        s = str(ele)
        over = len(s) - keep
        if over <= 0:
            for p in protected: ele.append(p)
            return
        marker = f' [TRUNCATED {over//1000}k chars]'
        inner = ele.decode_contents()
        tag_overhead = len(s) - len(inner)
        inner_keep = max(keep - tag_overhead - len(marker), 0)
        ele.clear()
        if inner_keep > 0:
            ele.append(BeautifulSoup(inner[:inner_keep], 'html.parser'))
        ele.append(NavigableString(marker))
        for p in protected: ele.append(p)
    total = len(str(soup))
    if total <= budget: return soup
    kids = [(c, len(str(c))) for c in soup.children if c.name and not (c.string and '[FAKE ELEMENT]' in c.string)]
    if not kids: return soup
    selflen = total - sum(l for _, l in kids)
    remaining_budget = max(budget - selflen, 0)
    tag = getattr(soup, 'name', '?')
    print(f'{indent}[smart_truncate] <{tag}> total={total} budget={budget} selflen={selflen} kids={len(kids)}')
    # === 1 kid: 穿透 ===
    if len(kids) == 1:
        print(f'{indent}  -> single child, recurse into <{kids[0][0].name}>')
        smart_truncate(kids[0][0], remaining_budget, _depth)
        return soup
    over = sum(l for _, l in kids) - remaining_budget
    if over <= 0: return soup
    # 看 top 3 能否承担 over
    ranked = sorted(range(len(kids)), key=lambda i: kids[i][1], reverse=True)
    tops = list(ranked[:min(3, len(ranked))])
    top_total = sum(kids[i][1] for i in tops)
    if top_total < over:
        # === top 3 扛不住，从尾部删子元素 ===
        removed = 0
        removed_count = 0
        while kids and removed < over:
            c, l = kids.pop(); c.decompose()
            removed += l; removed_count += 1
        print(f'{indent}  -> tail-cut: removed {removed_count} children ({removed//1000}k chars) from end')
        return soup
    # === top 2-3 按比例分担 ===
    # 过滤掉太小的 kid（不到最大的 10%），让大的全扛
    max_size = kids[ranked[0]][1]
    filtered = [i for i in tops if kids[i][1] >= max_size * 0.1]
    filtered_total = sum(kids[i][1] for i in filtered)
    if filtered_total >= over:
        tops, top_total = filtered, filtered_total
    # 先打印所有分配计划
    actions = []
    for i in tops:
        c, l = kids[i]
        share = int(over * l / top_total)
        new_keep = l - share
        print(f'{indent}  -> <{c.name}> {l} -> {new_keep} (share={share})')
        actions.append((c, l, new_keep))
    # 再统一执行
    for c, l, new_keep in actions:
        if new_keep <= 0: c.decompose()
        elif new_keep > CUT_THRESHOLD: smart_truncate(c, new_keep, _depth + 1)
        else: cut(c, new_keep)
    return soup

def execute_js_rich(script, driver, no_monitor=False):
    last_html = None
    if not no_monitor:
        try: last_html = get_html(driver, cutlist=False, extra_js=temp_monitor_js, maxchars=9999999)
        except: pass
    result = None;  error_msg = None;  reloaded = False; newTabs = []
    before_sids = set(driver.get_session_dict().keys()); response = {}
    try:
        print(f"Executing: {script[:250]} ...")
        response = driver.execute_js(script)
        result = response['data'] if 'data' in response else response.get('result')
        if response.get('closed', 0) == 1: reloaded = True
        time.sleep(1) 
    except Exception as e:
        error = e.args[0] if e.args else str(e)
        if isinstance(error, dict): error.pop('stack', None)
        error_msg = str(error)
        print(f"Error: {error_msg}")
    rr = {
        "status": "failed" if error_msg else "success",
        "js_return": result,
        "tab_id": driver.default_session_id
    }  
    if reloaded: rr['reloaded'] = reloaded
    if response.get('newTabs'): rr['newTabs'] = response['newTabs']
    else:
        after = driver.get_session_dict()
        new_sids = {k: v for k, v in after.items() if k not in before_sids}
        if new_sids:
            newTabs = [{'id': k, 'url': v} for k, v in new_sids.items()]
            rr['newTabs'] = newTabs
            rr['suggestion'] = "页面已刷新，以上新标签页在执行期间连接。"
    if error_msg: rr['error'] = error_msg
    if no_monitor: return rr
    if not reloaded:
        try: rr['transients'] = get_temp_texts(driver)
        except: rr['transients'] = []
    if not reloaded and len(newTabs) == 0:
        try:
            current_html = get_html(driver, cutlist=False, maxchars=9999999)
            if last_html is None: raise Exception("no baseline")
            diff_data = find_changed_elements(last_html, current_html)
            change_count = diff_data.get('changed', 0)
            top_change = diff_data.get('top_change', '')
            diff_summary = f"DOM变化量: {change_count}"
            if top_change: diff_summary += f"\n最显著变化:\n{top_change}"
            transients = rr.get('transients', [])
            if change_count == 0 and not transients and len(newTabs) == 0:
                diff_summary += " (页面无变化)"
                rr['suggestion'] = "页面无明显变化"
        except:
            diff_summary = "页面变化监控不可用"
        rr['diff'] = diff_summary
    return rr
