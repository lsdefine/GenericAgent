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
          
    if (!isVisible && nonTextChildren.length > 0) {
      const visChild = nonTextChildren.find(child => 
          nodeInfo.has(child) && nodeInfo.get(child).isVisible);
      if (visChild) info = nodeInfo.get(visChild);
    }
    nodeInfo.set(clone, info);

    if (sourceNode.nodeType === 1 && sourceNode.tagName === 'DIV') {    
      if (!hasValidChildren && !sourceNode.textContent.trim()) return null; 
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
    const pathType = (node.dataset.mark && !node.dataset.mark.includes(':main')) ? 'second' : pPathType;  
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
          area: info.area, zIndex: info.zIndex };  
    }).sort((a, b) => b.area - a.area);  
    
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
      for (let i = pathType==='main'?1:0; i < childrenInfo.length; i++) {  
        const child = childrenInfo[i];  
        let isSecondary = containsButton(child.node);
        if (pathType === "main" && child.node.className.toLowerCase().includes('nav')) isSecondary = true;
        if (pathType === "main" && child.node.className.toLowerCase().includes('breadcrumbs')) isSecondary = true;
        if (pathType === "main" && child.node.className.toLowerCase().includes('header') && child.node.className.toLowerCase().includes('table')) isSecondary = true;
        if (pathType === "main" && child.node.innerHTML.trim().replace(/\s+/g, '').length < 500) isSecondary = true;
        if (child.style.visibility === 'hidden') isSecondary = false;
        if (isSecondary) child.node.dataset.mark = 'K:secondary';  
        else child.node.dataset.mark = 'R:nonEssential';  
      }  
    } else {  
      const uniqueClassNames = new Set(childrenInfo.map(item => item.node.className)).size;  
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
    const isDialog = top.node.querySelector('iframe') && centerDiff < 0.3;

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
        return !(r1.x + r1.width <= r2.x + epsilon || r1.x >= r2.x + r2.width - epsilon || 
            r1.y + r1.height <= r2.y + epsilon || r1.y >= r2.y + r2.height - epsilon
        );
      })
    );  
}

const result = analyzeNode(domCopy); 
domCopy.querySelectorAll('[data-mark^="R:"]').forEach(el=>el.parentNode?.removeChild(el));  
let root = domCopy;  
while (root.children.length === 1) {  
  root = root.children[0];  
}  
for (let ii = 0; ii < 3; ii++) 
  root.querySelectorAll('div').forEach(div => (!div.textContent.trim() && div.children.length === 0) && div.remove());
root.querySelectorAll('[data-mark]').forEach(e => e.removeAttribute('data-mark'));  
root.removeAttribute('data-mark');  
return root.outerHTML;
    }
optHTML()'''

js_findMainList = r'''function findMainList(startElement = null) {
        const containerElement = startElement || document.body;  
        const rect = containerElement.getBoundingClientRect();  
        const centerX = startElement ? (rect.left + rect.width/2) : (window.innerWidth/2);  
        const centerY = startElement ? (rect.top + rect.height/2) : (window.innerHeight/2);  
        
        // 获取中心元素  
        const centerElement = document.elementFromPoint(centerX, centerY) || containerElement;  
        if (!centerElement) return { container: null, items: [] };  

        // 收集祖先链  
        const ancestors = [];  
        for (let current = centerElement; current && ancestors.length < 10; current = current.parentElement) {  
            ancestors.push(current);  
            if (current === containerElement) break;  
            if (containerElement !== document.body && !containerElement.contains(current)) break;  
        }  
        if (!ancestors.includes(containerElement)) ancestors.push(containerElement);  

        let groupCandidates = [];
        ancestors.forEach(ancestor => {
            const topGroups = findTopGroups(ancestor, 3);
            groupCandidates = groupCandidates.concat(topGroups);
        });

        console.log(groupCandidates);

        let candidates = [];
        ancestors.forEach(container => {
            groupCandidates.forEach(groupInfo => {
                // 尝试将组应用到当前容器
                const items = findMatchingElements(container, groupInfo.selector);
                // 只考虑足够大的组
                if (items.length >= 3) {
                    candidates.push({
                        container: container,
                        selector: groupInfo.selector,
                        items: items,
                        gscore: groupInfo.score
                    });
                }
            });
        });

        candidates = candidates.map(candidate => {
            const score = scoreContainer(candidate.container, candidate.items) + candidate.gscore;
            return {...candidate, score};
        });

        if (candidates.length === 0) {
            return { container: centerElement, items: [] };
        }

        // 3. 选择得分最高的容器
        const bestCandidate = candidates.sort((a, b) => b.score - a.score)[0];
        console.log(candidates);

        // 如果最高分仍然很低，退回到中心元素
        if (bestCandidate.score < 30) {
            return { container: centerElement, items: [] };
        }

        return {
            container: bestCandidate.container,
            items: bestCandidate.items,
            selector: bestCandidate.selector,
            score: bestCandidate.score
        };
    }
    
    function findTopGroups(container, limit) {
        const children = Array.from(container.children);
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
                const selector = '.' + cls;
                groups.push({
                    selector,
                    elements: classMap[cls],
                    score: scoreGroup(selector, classMap[cls])
                });
            }
        });
        // 添加标签+类组合
        const topTags = Object.keys(tagFreq)
            .filter(t => tagFreq[t] >= minGroupSize)
            .slice(0, 3);

        const topClasses = Object.keys(classFreq)
            .filter(c => classFreq[c] >= minGroupSize)
            .sort((a, b) => classFreq[b] - classFreq[a])
            .slice(0, 3);

        // 标签+类
        topTags.forEach(tag => {
            topClasses.forEach(cls => {
                const elements = children.filter(el =>
                                                 el.tagName.toLowerCase() === tag &&
                                                 el.className && el.className.split(/\s+/).includes(cls)
                                                );

                if (elements.length >= minGroupSize) {
                    const selector = tag + '.' + cls;
                    groups.push({
                        selector,
                        elements,
                        score: scoreGroup(selector, elements)
                    });
                }
            });
        });

        // 多类组合
        for (let i = 0; i < topClasses.length; i++) {
            for (let j = i + 1; j < topClasses.length; j++) {
                const elements = children.filter(el =>
                                                 el.className &&
                                                 el.className.split(/\s+/).includes(topClasses[i]) &&
                                                 el.className.split(/\s+/).includes(topClasses[j])
                                                );

                if (elements.length >= minGroupSize) {
                    const selector = '.' + topClasses[i] + '.' + topClasses[j];
                    groups.push({
                        selector,
                        elements,
                        score: scoreGroup(selector, elements)
                    });
                }
            }
        }
        // 返回得分最高的N个组
        return groups
            .sort((a, b) => b.score - a.score)
            .slice(0, limit);
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
            if (uniqueRows === 1 || uniqueCols === 1) {
                layoutScore = 20;
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

js_findMainContent = '''
  function isLikelyOperationMenu(element) {  
    // 基础尺寸和位置检查  
    const rect = element.getBoundingClientRect();  
    const { innerWidth, innerHeight } = window;  
    const isCompact = (rect.width * rect.height) < (innerWidth * innerHeight * 0.15);  
    if (!isCompact) return false;  
    
    // 边缘检测  
    const edgeProximity = {  
      top: rect.top < 100,  
      left: rect.left < 50,  
      right: innerWidth - rect.right < 50,  
      bottom: innerHeight - rect.bottom < 100  
    };  
    const isAtEdge = Object.values(edgeProximity).some(Boolean);  
    
    // 交互元素分析  
    const links = [...element.querySelectorAll('a')];  
    const buttons = [...element.querySelectorAll('button, [role="button"]')];  
    const allInteractive = [...links, ...buttons];  
    
    // 快速排除: 边缘较大元素通常是导航  
    if (isAtEdge && rect.width > 150 && rect.height > 50 && links.length > 3) {  
      return false;  
    }  
    
    // 链接类型分析  
    const linkTypes = links.reduce((types, link) => {  
      const href = link.getAttribute('href') || '';  
      if (href.startsWith('#')) types.hash++;  
      else if (href.startsWith('javascript:')) types.js++;  
      else if (href.includes('://') && !href.includes(location.hostname)) types.external++;  
      else types.internal++;  
      return types;  
    }, { hash: 0, js: 0, external: 0, internal: 0 });  
    
    // 特征评分  
    const operationFeatures = [  
      linkTypes.hash > 0 || linkTypes.js > 0,  // 页内操作链接  
      buttons.length > 0,                      // 有按钮  
      buttons.length > 1,
      rect.width > rect.height * 1.5 && allInteractive.length <= 6,  // 水平排列且元素适量  
      element.querySelectorAll('svg, img, i, [class*="icon"]').length > 0,  // 有图标  
      getComputedStyle(element).position !== 'static' && !isAtEdge  // 定位但不在边缘  
    ];  
    const navigationFeatures = [  
      isAtEdge,                           // 在页面边缘  
      linkTypes.internal > 3,             // 多个内部页面链接  
      links.length === allInteractive.length && links.length > 3  // 全是链接且数量多  
    ];  
    const opScore = operationFeatures.filter(Boolean).length;  
    const navScore = navigationFeatures.filter(Boolean).length;  
    return opScore > 1 && opScore > navScore;  
  }  

  function getFirstVisibleRect(el) {  
    const rect = el.getBoundingClientRect();  
    
    if (rect.width > 0 && rect.height > 0) {  
        return {  
            left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,  
            width: rect.width, height: rect.height, x: rect.x, y: rect.y,  
            zIndex: parseInt(getComputedStyle(el).zIndex) || 0  
        };  
    }  
    
    if (!el.querySelector('button, a, input') || !el.innerText.trim()) return rect;  
    
    const visibleChild = Array.from(el.children)  
        .find(child => {  
            const hasContent = child.querySelector('button, a, input') && child.innerText.trim();  
            return hasContent && (  
                child.getBoundingClientRect().width > 0 ||   
                getFirstVisibleRect(child).width > 0  
            );  
        });  
        
    if (!visibleChild) return rect;  
    
    const childRect = visibleChild.getBoundingClientRect();  
    return childRect.width > 0 ?   
        {  
            left: childRect.left, top: childRect.top, right: childRect.right, bottom: childRect.bottom,  
            width: childRect.width, height: childRect.height, x: childRect.x, y: childRect.y,  
            zIndex: parseInt(getComputedStyle(visibleChild).zIndex) || 0  
        } :   
        getFirstVisibleRect(visibleChild);  
  }  

  function findMainContent(node) {  
    if (!node?.children?.length) return node;  
    const rectn = node.getBoundingClientRect();
    const viewportArea = window.innerWidth * window.innerHeight;  
    if (rectn.width * rectn.height < viewportArea * 0.4) return node;
    
    // 过滤可见元素  
    const children = [...node.children].filter(child => {  
      const style = window.getComputedStyle(child);  
      const hasTextContent = child.textContent.trim().length > 5; 
      return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && hasTextContent;  
    });  
    if (!children.length) return node;  
    if (children.length === 1) return findMainContent(children[0]);  
    if (children.length > 10) return node;
    if (children.length == 2 && (isLikelyOperationMenu(children[0]) || isLikelyOperationMenu(children[1]))) return node;

    // 计算元素信息  
    const elemInfo = children.map(child => {  
      const rect = getFirstVisibleRect(child);   
      const style = window.getComputedStyle(child);  
      return {   
        element: child, area: rect.width * rect.height, rect, style,
        zIndex: rect.zIndex || 0, position: style.position  
      };  
    }).sort((a, b) => b.area - a.area);      
    // 检测重叠  
    function isOverlapping(r1, r2) {  
      return !(r1.right <= r2.left || r1.left >= r2.right || r1.bottom <= r2.top || r1.top >= r2.bottom);  
    }  
    // 检查是否有任何重叠的元素对  
    const hasOverlap = elemInfo.some((e1, i) =>   
      elemInfo.slice(i + 1).some(e2 => isOverlapping(e1.rect, e2.rect))  
    );  
    
    console.log(hasOverlap, elemInfo);
    
    // 无重叠情况: 面积比例判断  
    if (!hasOverlap) {  
      const totalArea = elemInfo.reduce((sum, item) => sum + item.area, 0);  
      const [main, second] = elemInfo;  
      return (main.area / totalArea > 0.6 && (!second || main.area > second.area * 2))   
        ? findMainContent(main.element) : node;  
    }  
                      
    // 1. 按z-index和定位方式排序  
    const sorted = [...elemInfo].sort((a, b) => {  
        // 非静态定位优先  
        if (a.position !== 'static' && b.position === 'static') return -1;  
        if (a.position === 'static' && b.position !== 'static') return 1;  
        // 其次按z-index排序  
        return b.zIndex - a.zIndex;  
    });  

    // 2. 在排序后的列表中找到第一个符合条件的元素  
    const suitable = sorted.find(x => {  
        const el = x.element, rect = x.rect, style = x.style;
        return Math.abs((rect.left + rect.width/2) - window.innerWidth/2) < window.innerWidth*0.3 &&  
               parseFloat(style.opacity) > 0.1 &&  
               (parseInt(rect.zIndex) > 30 || style.boxShadow !== 'none') &&  
               el.querySelector('button, a, input') !== null;  
    });  
    
    // 3. 找到合适元素则使用它，否则返回面积最大的元素  
    if (suitable) {  
        return findMainContent(suitable.element);  
    } else {  
        const byArea = [...elemInfo].sort((a, b) => b.area - a.area);  
        return findMainContent(byArea[0].element);  
    }  
  }  '''

def optimize_html_for_tokens(html):  
    if type(html) is str: soup = BeautifulSoup(html, 'html.parser')  
    else: soup = html
    for svg in soup.find_all('svg'): svg.clear()
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
    
import time, re
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

def get_html(driver, cutlist=False, maxchars=38000, instruction="", extra_js="", text_only=False):
    page = get_main_block(driver, extra_js=extra_js, text_only=text_only)
    if text_only: return page
    soup = optimize_html_for_tokens(page)
    html = str(soup)
    if not cutlist or len(html) <= maxchars: return html
    rr = driver.execute_js(js_findMainList + js_findMainContent + """
        return findMainList(findMainContent(document.body));""").get('data', {})
    sel = rr.get("selector", None) if isinstance(rr, dict) else None
    if sel: 
        s = BeautifulSoup(str(soup), "html.parser"); items = s.select(sel)
        hit = [it for it in items if instruction and instruction.strip() and instruction in it.get_text(" ",strip=True)]
        keep = hit[:6] if hit else items[:3]
        for it in items:
            if it not in keep: it.decompose()
        ss = '[SYSTEM] Found item list, only show some items ...\n' + str(optimize_html_for_tokens(s))
    else: ss = html
    if len(ss) > maxchars: ss = ss[:maxchars] + ' ... [TRUNCATED]'
    return ss

def execute_js_rich(script, driver, no_monitor=False):
    last_html = None
    if not no_monitor:
        try: last_html = get_html(driver, cutlist=False, extra_js=temp_monitor_js, maxchars=9999999)
        except: pass
    result = None;  error_msg = None;  reloaded = False; newTabs = []
    before_sids = set(driver.get_session_dict().keys())
    try:
        print(f"Executing: {script[:250]} ...")
        response = driver.execute_js(script)
        result = response.get('data') or response.get('result')
        if response.get('closed', 0) == 1: reloaded = True
        time.sleep(2) 
    except Exception as e:
        error = e.args[0] if e.args else str(e)
        if isinstance(error, dict): error.pop('stack', None)
        error_msg = str(error)
        print(f"Error: {error_msg}")
    rr = {
        "status": "failed" if error_msg else "success",
        "js_return": result,
        "environment": {"reloaded": reloaded},
        "tab_id": driver.default_session_id
    }  
    after = driver.get_session_dict()
    new_sids = {k: v for k, v in after.items() if k not in before_sids}
    if new_sids:
        newTabs = [{'id': k, 'url': v} for k, v in new_sids.items()]
        rr['environment']['newTabs'] = newTabs
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
