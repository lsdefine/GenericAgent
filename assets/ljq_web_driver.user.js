// ==UserScript==
// @name         ljq_web_driver
// @namespace    http://tampermonkey.net/
// @version      0.40
// @description  Execute JS via ljq_web_driver
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @author       You
// @match        *://*/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_xmlhttpRequest
// @grant        GM_openInTab
// @grant        unsafeWindow
// @connect      127.0.0.1
// @run-at       document-start
// ==/UserScript==


(function() {
    'use strict';
    const log_prefix = "ljq_driver: ";
    if (document.querySelector('[data-testid="stApp"],.stApp')) return;
    if (/<title>\s*Streamlit\s*<\/title>|window\.prerenderReady=!1|You need to enable JavaScript to run this app\./i.test(document.documentElement?.outerHTML || '')) return;
    
    if (window.self !== window.top) {
        window.addEventListener('message',e=>{if(e.data?.type==='ljq_exec'){try{let r=eval(e.data.code);parent.postMessage({type:'ljq_result',id:e.data.id,result:String(r)},'*')}catch(err){parent.postMessage({type:'ljq_result',id:e.data.id,error:err.message},'*')}}});
        return;
    }

    const wsUrl = 'ws://127.0.0.1:18765';
    const httpUrl = 'http://127.0.0.1:18766/';
    
    function isWebSocketServerAlive(callback) {
        GM_xmlhttpRequest({
            method: 'GET',
            url: 'http://127.0.0.1:18765/',
            onload: () => callback(true),
            onerror: () => callback(false)
        });
    }

    let ws;
    let sid;
    if (window.opener && window.name && window.name.startsWith('ljq_')) {
        sid = null;
        console.log(log_prefix + `检测到opener，丢弃继承的window.name: ${window.name}`);
        window.name = '';
    } else {
        sid = (window.name && window.name.startsWith('ljq_')) ? window.name : null;
    }
    if (!sid) {
        sid = `ljq_${Date.now().toString().slice(-2)}${Math.random().toString(36).slice(2, 4)}`;
        window.name = sid;
        console.log(log_prefix + `创建新会话ID: ${sid}`);
    } else {
        console.log(log_prefix + `使用现有会话ID: ${sid}`);
    }

    // 保存会话ID
    GM_setValue('sid', sid);

    // 获取或创建状态指示器
    function getIndicator() {
        // 检查现有指示器
        let ind = document.getElementById('ljq-ind');

        // 删除重复指示器
        const dups = document.querySelectorAll('[id="ljq-ind"]');
        if (dups.length > 1) {
            for (let i = 1; i < dups.length; i++) {
                dups[i].remove();
            }
            ind = dups[0];
        }

        // 创建新指示器
        if (!ind && document.body) {
            ind = document.createElement('div');
            ind.id = 'ljq-ind';
            ind.style.cssText = `
                position: fixed;bottom: 10px;
                right: 10px;background-color: #f44336;
                color: white;padding: 8px 12px;
                border-radius: 6px;font-size: 14px;
                font-weight: bold;z-index: 9999;
                transition: background-color 0.3s;
                cursor: pointer;box-shadow: 0 3px 6px rgba(0,0,0,0.25);
            `;
            ind.innerText = log_prefix + '正在连接...';

            ind.addEventListener('click', () => alert(`会话ID: ${sid}\n当前URL: ${location.href}`));
            document.body.appendChild(ind);
        }

        return ind;
    }

    // 更新状态
    function updateStatus(status, msg) {
        if (!document.body) return setTimeout(() => updateStatus(status, msg), 100);

        const ind = getIndicator();
        if (!ind) return;

        if (status === 'ok') {
            ind.style.backgroundColor = '#4CAF50';
            ind.innerText = log_prefix + '连接成功';
        } else if (status === 'disc') {
            ind.style.backgroundColor = '#f44336';
            ind.innerText = log_prefix + '连接断开';
        } else if (status === 'conn') {
            ind.style.backgroundColor = '#2196F3';
            ind.innerText = log_prefix + '正在连接(HTTP)';
        } else if (status === 'err') {
            ind.style.backgroundColor = '#FF9800';
            ind.innerText = log_prefix + `发生错误 (${msg})`;
        } else if (status === 'exec') {
            ind.style.backgroundColor = '#2196F3';
            ind.innerText = log_prefix + '正在执行指令...';
        }
    }

    function handleError(id, error, errorSource) {
        console.error(`${errorSource}错误:`, error);
        updateStatus('err', error.message);

        const errorMessage = {
            type: 'error',
            id: id,
            sessionId: sid,
            error: {
                name: error.name,
                message: error.message,
                stack: error.stack,
                source: errorSource
            }
        };

        if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(errorMessage));
        } else {
            GM_xmlhttpRequest({
                method: "POST",
                url: httpUrl + "api/result",
                headers: {"Content-Type": "application/json"},
                data: JSON.stringify(errorMessage),
                onload: function(response) {console.log("错误信息已通过HTTP发送", response);},
                onerror: function(err) {console.error("发送错误信息失败", err);}
            });
        }
    }

    function smartProcessResult(result) {
        // 处理 null 和原始类型
        if (result === null || result === undefined || typeof result !== 'object') {
            return result;
        }

        // 1. 处理 jQuery 对象 - 强制转换为HTML字符串数组
        if (typeof jQuery !== 'undefined' && result instanceof jQuery) {
            const elements = [];
            for (let i = 0; i < result.length; i++) {
                if (result[i] && result[i].nodeType === 1) {
                    elements.push(result[i].outerHTML);
                }
            }
            return elements; // 始终返回数组
        }

        // 2. 处理 NodeList 和 HTMLCollection
        if (result instanceof NodeList || result instanceof HTMLCollection) {
            const elements = [];
            for (let i = 0; i < result.length; i++) {
                if (result[i] && result[i].nodeType === 1) {
                    elements.push(result[i].outerHTML);
                }
            }
            return elements;
        }

        // 3. 处理单个 DOM 元素
        if (result.nodeType === 1) {
            return result.outerHTML;
        }

        // 4. 检查是否是具有数字索引和length属性的类数组对象
        if (!Array.isArray(result) &&
            typeof result === 'object' &&
            'length' in result &&
            typeof result.length === 'number') {

            // 检查第一个元素是否是DOM节点
            const firstElement = result[0];
            if (firstElement && firstElement.nodeType === 1) {
                const elements = [];
                const length = Math.min(result.length, 100);

                for (let i = 0; i < length; i++) {
                    const elem = result[i];
                    if (elem && elem.nodeType === 1) {
                        elements.push(elem.outerHTML);
                    }
                }

                return elements;
            }
        }

        // 5. 处理普通对象和数组 - 使用标准序列化
        try {
            return JSON.parse(JSON.stringify(result, function(key, value) {
                if (typeof value === 'object' && value !== null) {
                    if (value.nodeType === 1) {
                        return value.outerHTML;
                    }
                    if (value === window || value === document) {
                        return '[Object]';
                    }
                }
                return value;
            }));
        } catch (e) {
            console.error("序列化对象失败:", e);
            return `[无法序列化的对象: ${e.message}]`;
        }
    }

    // 防止重复初始化
    if (window.ljq_init) return;
    window.ljq_init = true;

    function connecthttp() {
        if (window.use_ws) return;
        updateStatus('conn');
        GM_xmlhttpRequest({
            method: "POST",
            url: httpUrl + "api/longpoll",
            headers: {"Content-Type": "application/json"},
            data: JSON.stringify({
                type: 'ready',
                url: location.href,
                sessionId: sid
            }),
            onload: async function(resp) {
                if (resp.status === 200) {
                    let data = JSON.parse(resp.responseText);
                    console.log(log_prefix + '接收到数据:', data);
                    if (data.id === "" && data.ret === "use ws") return;
                    if (data.id === "") return setTimeout(connecthttp, 100);
                    const response = await executeCode(data);

                    if (response.error) {
                        handleError(data.id, response.error, '执行代码');
                    } else {
                       GM_xmlhttpRequest({
                           method: "POST",
                           url: httpUrl + "api/result",
                           headers: {"Content-Type": "application/json"},
                           data: JSON.stringify({
                               type: 'result',
                               id: data.id,
                               sessionId: sid,
                               result: response.result
                           })
                       });
                    }
                } else {
                    console.error(log_prefix + '请求失败，状态码：', resp.status);
                    updateStatus('err', '请求失败');
                }
                setTimeout(connecthttp, 1000);
            },
            onerror: function(err) {
                console.error(log_prefix + '请求错误', err);
                updateStatus('err', '请求失败');
                setTimeout(connecthttp, 5000);
            },
            ontimeout: function() {
                console.log(log_prefix + '请求超时');
                updateStatus('err', '请求超时');
                setTimeout(connecthttp, 5000);
            }
        });
    }

    async function executeCode(data) {
        let id = data.id || 'unknown'; // 获取 ID
        let result;

        if (!data.code) {
            console.log('收到非代码执行消息:', data);
            return { error: '没有可执行的代码' };
        }
        updateStatus('exec');
        const _open = window.open;
        window.open = (url, target, features) => {
            GM_openInTab(url, { active: true });
            return { success: true, url: url };
        };
        try {
            const jsCode = data.code.trim();
            const lines = jsCode.split(/\r?\n/).filter(l => l.trim());
            const lastLine = lines.length > 0 ? lines[lines.length - 1].trim() : '';
            const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
            
            if (lastLine.startsWith('return')) {
                result = await (new AsyncFunction(jsCode))();
            } else {
                try {
                    result = eval(jsCode);
                    if (result instanceof Promise) result = await result;
                } catch (e) {
                    if (isIllegalReturnError(e) || isAwaitError(e)) {
                        result = await (new AsyncFunction(jsCode))();
                    } else throw e; 
                }
            }
            const processedResult = smartProcessResult(result);
            return { result: processedResult }; 
        } catch (execError) {
            return { error: execError }; 
        } finally {
            setTimeout(() => window.open = _open, 100);
        }
    }

    function isIllegalReturnError(e) {
        return e instanceof SyntaxError && (
            /Illegal return statement/i.test(e.message) ||      // Chrome 常见
            /return not in function/i.test(e.message) ||        // Firefox 常见
            /Illegal 'return' statement/i.test(e.message)       // 兼容旧文案
        );
    }

    function isAwaitError(e) {
        return e instanceof SyntaxError && (
            /await is only valid in async/i.test(e.message) ||  // Chrome
            /await.*async/i.test(e.message)                     // Firefox等
        );
    }

    function connect() {
        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            window.use_ws = true;
            console.log(log_prefix + '已连接');
            updateStatus('ok');
            ws.send(JSON.stringify({
                type: 'ready',
                url: location.href,
                sessionId: sid
            }));
        };

        ws.onclose = function() {
            console.log(log_prefix + '已断开，5秒后重连');
            updateStatus('disc');
            setTimeout(connect, 5000);
        };

        ws.onerror = function(err) {
            console.error(log_prefix + '连接错误', err);
            updateStatus('err', '连接失败');
            isWebSocketServerAlive(function (e) { if (e) connecthttp()});
        };

        ws.onmessage = async function(e) {
            try {
                let data = JSON.parse(e.data);
                ws.send(JSON.stringify({type: 'ack',id: data.id}));
                const response = await executeCode(data);
             
                if (response.error) {
                    handleError(data.id, response.error, '执行代码');
                } else {
                    updateStatus('ok');  
                    ws.send(JSON.stringify({
                        type: 'result',
                        id: data.id,
                        sessionId: sid,
                        result: response.result
                    }));
                }
            } catch (parseError) {
                handleError('unknown', parseError, '解析消息');
            }
        };

    }

    // 初始化
    function init() {
        if (document.body) {
            getIndicator();
            connect();
        } else {
            setTimeout(init, 50);
        }
    }

    // 监控DOM变化 (改为10秒定时器以优化性能)
    let indicatorTimer = null;

    if (document.readyState !== 'loading') {
        init();
        indicatorTimer = setInterval(() => getIndicator(), 10000);
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            init();
            indicatorTimer = setInterval(() => getIndicator(), 10000);
        });
    }

    // 清理
    window.addEventListener('beforeunload', () => {
        if (indicatorTimer) clearInterval(indicatorTimer);
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
        }
    });
})();