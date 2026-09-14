document.addEventListener('DOMContentLoaded', () => {

    // ==================== 共享工具函数 ====================

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    async function apiFetch(method, path, body = null) {
        const options = { method, headers: {} };
        if (body && method !== 'GET') {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        const resp = await fetch(path, options);
        return await resp.json();
    }

    function extractElement(apiResponse) {
        return apiResponse?.element || apiResponse?.data?.element || null;
    }

    // ==================== 标签页切换 ====================

    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    function switchTab(tabId) {
        tabBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.tab === tabId));
        tabContents.forEach(content => content.classList.toggle('active', content.id === tabId));

        // 离开 Tab1 时停止自动刷新，避免后台空跑浪费资源
        if (tabId !== 'tab1' && isAutoRefreshing) {
            stopAutoRefresh();
            autoRefreshToggle.checked = false;
        }

        if (tabId === 'tab2') loadDesignAll();
        if (tabId === 'tab3') refreshGenPreview();
    }

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // ==================== Tab1: 元素抓取（保留现有逻辑） ====================

    const statusIndicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    const deviceName = document.getElementById('device-name');
    const btnConnect = document.getElementById('btn-connect');
    const btnDisconnect = document.getElementById('btn-disconnect');
    const btnRefreshScreenshot = document.getElementById('btn-refresh-screenshot');
    const btnRefreshElements = document.getElementById('btn-refresh-elements');
    const autoRefreshToggle = document.getElementById('auto-refresh-toggle');
    const autoRefreshInterval = document.getElementById('auto-refresh-interval');
    const screenshotContainer = document.getElementById('screenshot-container');
    const screenshotImg = document.getElementById('screenshot-img');
    const elementsContainer = document.getElementById('elements-container');
    const elementList = document.getElementById('element-list');
    const detailPanel = document.getElementById('detail-panel');
    const btnCloseDetail = document.getElementById('btn-close-detail');
    const btnMock = document.getElementById('btn-mock');
    const modeIndicator = document.getElementById('mode-indicator');

    const inputDeviceUsb = document.getElementById('input-device-usb');
    const inputDeviceWifi = document.getElementById('input-device-wifi');
    const inputPairCode = document.getElementById('input-pair-code');
    const radioButtons = document.querySelectorAll('input[name="connect-method"]');

    let currentDetailElement = null;
    let currentElements = [];
    let selectedElementId = null;
    let highlightBox = null;

    function getConnectMethod() {
        const checked = document.querySelector('input[name="connect-method"]:checked');
        return checked ? checked.value : 'usb';
    }

    radioButtons.forEach(radio => {
        radio.addEventListener('change', () => {
            const method = getConnectMethod();
            if (method === 'wifi') {
                inputDeviceUsb.style.display = 'none';
                inputDeviceWifi.style.display = 'block';
                inputPairCode.style.display = 'inline-block';
            } else {
                inputDeviceUsb.style.display = 'block';
                inputDeviceWifi.style.display = 'none';
                inputPairCode.style.display = 'none';
            }
        });
    });

    function getDeviceNameInput() {
        const method = getConnectMethod();
        const input = method === 'wifi' ? inputDeviceWifi : inputDeviceUsb;
        return input.value.trim();
    }

    function setConnectControlsDisabled(disabled) {
        inputDeviceUsb.disabled = disabled;
        inputDeviceWifi.disabled = disabled;
        inputPairCode.disabled = disabled;
        radioButtons.forEach(r => r.disabled = disabled);
    }

    function setConnected(connected, name = '', mode = 'disconnected') {
        if (connected) {
            statusIndicator.classList.add('connected');
            statusText.textContent = '已连接';
            deviceName.textContent = name || '';
            btnConnect.disabled = true;
            btnDisconnect.disabled = false;
            btnMock.disabled = true;
            setConnectControlsDisabled(true);
            modeIndicator.className = 'mode-indicator ' + mode;
            modeIndicator.textContent = mode === 'real' ? '真实设备' : '模拟模式';
            modeIndicator.style.display = 'inline-block';
        } else {
            statusIndicator.classList.remove('connected');
            statusText.textContent = '未连接';
            deviceName.textContent = '';
            btnConnect.disabled = false;
            btnDisconnect.disabled = true;
            btnMock.disabled = false;
            setConnectControlsDisabled(false);
            modeIndicator.style.display = 'none';
        }
    }

    btnMock.addEventListener('click', async () => {
        try {
            btnMock.disabled = true;
            if (btnMock.classList.contains('active')) {
                const resp = await fetch('/api/mock/disable', { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    btnMock.classList.remove('active');
                    btnMock.textContent = '启用模拟模式';
                    setConnected(false);
                }
            } else {
                const resp = await fetch('/api/mock/enable', { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    btnMock.classList.add('active');
                    btnMock.textContent = '退出模拟模式';
                    setConnected(true, '模拟设备', 'mock');
                }
            }
        } catch (err) {
            console.error('模拟模式切换失败', err);
            alert('模拟模式切换失败');
            btnMock.disabled = false;
        }
    });

    async function fetchDeviceStatus() {
        try {
            const resp = await fetch('/api/device/status');
            const data = await resp.json();
            if (data.connected) {
                const mode = data.mode || 'real';
                if (mode === 'mock') {
                    btnMock.classList.add('active');
                    btnMock.textContent = '退出模拟模式';
                }
                const displayName = data.device_name || data.device?.name || data.device?.udid || '';
                setConnected(true, displayName, mode);
            } else {
                btnMock.classList.remove('active');
                btnMock.textContent = '启用模拟模式';
                setConnected(false);
            }
        } catch (err) {
            console.error('获取设备状态失败', err);
        }
    }

    btnConnect.addEventListener('click', async () => {
        try {
            btnConnect.disabled = true;
            const method = getConnectMethod();
            const deviceNameInput = getDeviceNameInput();
            const payload = { method };
            if (deviceNameInput) payload.device_name = deviceNameInput;
            if (method === 'wifi') {
                const pairCode = inputPairCode.value.trim();
                if (pairCode) payload.pair_code = pairCode;
            }
            const resp = await fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            if (data.success) {
                if (data.mode === 'real') {
                    setConnected(true, data.device.name, 'real');
                } else {
                    setConnected(true, data.device.name, data.mode || 'mock');
                }
            } else {
                alert(data.message || '连接失败');
                btnConnect.disabled = false;
            }
        } catch (err) {
            console.error('连接失败', err);
            alert('连接请求出错');
            btnConnect.disabled = false;
        }
    });

    btnDisconnect.addEventListener('click', async () => {
        try {
            btnDisconnect.disabled = true;
            const resp = await fetch('/api/disconnect', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                setConnected(false);
            } else {
                alert(data.message || '断开失败');
            }
        } catch (err) {
            console.error('断开失败', err);
            alert('断开请求出错');
        }
    });

    async function loadScreenshot() {
        try {
            const resp = await fetch('/api/screenshot?t=' + Date.now());
            if (!resp.ok) throw new Error('截图加载失败: ' + resp.status);
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const oldPrevUrl = screenshotImg.dataset.prevUrl;
            screenshotImg.src = url;
            screenshotImg.dataset.prevUrl = url;
            screenshotImg.style.display = 'block';
            screenshotImg.onload = () => {
                if (oldPrevUrl && oldPrevUrl !== url) URL.revokeObjectURL(oldPrevUrl);
                if (currentDetailElement?.bounds) drawHighlightBox(currentDetailElement.bounds);
            };
            const placeholder = screenshotContainer.querySelector('.placeholder-box');
            if (placeholder) placeholder.style.display = 'none';
        } catch (err) {
            console.error('刷新截图失败', err);
            alert('刷新截图失败: ' + err.message);
        }
    }

    btnRefreshScreenshot.addEventListener('click', loadSnapshot);

    async function loadElements() {
        try {
            const resp = await fetch('/api/elements/refresh', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                renderElementList(data.elements);
            } else {
                alert(data.message || '获取元素失败');
            }
        } catch (err) {
            console.error('获取元素数据失败', err);
            alert('获取元素数据请求出错');
        }
    }

    // ===== 同源快照（Phase 5）：元素树与截图来自同一帧，消除坐标/高亮错位 =====
    let snapshotAvailable = true;  // /api/snapshot 不可用时自动回退旧双接口

    function applyScreenshotDataUrl(dataUrl) {
        screenshotImg.src = dataUrl;
        screenshotImg.style.display = 'block';
        screenshotImg.onload = () => {
            if (currentDetailElement?.bounds) drawHighlightBox(currentDetailElement.bounds);
        };
        const placeholder = screenshotContainer.querySelector('.placeholder-box');
        if (placeholder) placeholder.style.display = 'none';
    }

    async function fetchSnapshot() {
        const resp = await fetch('/api/snapshot?t=' + Date.now());
        if (!resp.ok) throw new Error('快照请求失败: ' + resp.status);
        const data = await resp.json();
        if (!data.success) throw new Error(data.message || '快照获取失败');
        const payload = data.data || {};
        renderElementList(payload.elements || []);
        if (payload.screenshot) {
            applyScreenshotDataUrl('data:image/png;base64,' + payload.screenshot);
        }
    }

    // 静默刷新：优先快照，失败自动降级到旧的截图+元素双请求
    async function refreshSilent() {
        if (snapshotAvailable) {
            try {
                await fetchSnapshot();
                return;
            } catch (err) {
                console.warn('快照接口不可用，降级到旧接口:', err.message);
                snapshotAvailable = false;
            }
        }
        await Promise.all([loadScreenshotSilent(), loadElementsSilent()]);
    }

    // 手动刷新（带错误提示）
    async function loadSnapshot() {
        try {
            await refreshSilent();
        } catch (err) {
            console.error('刷新失败', err);
            alert('刷新失败: ' + err.message);
        }
    }

    function renderElementList(elements) {
        currentElements = Array.isArray(elements) ? elements : [];
        elementList.innerHTML = '';
        if (currentElements.length === 0) {
            elementList.style.display = 'none';
            const placeholder = elementsContainer.querySelector('.placeholder-box');
            if (placeholder) placeholder.style.display = 'block';
            selectedElementId = null;
            currentDetailElement = null;
            detailPanel.style.display = 'none';
            clearHighlight();
            return;
        }
        currentElements.forEach(elem => {
            const li = document.createElement('li');
            li.className = 'element-item' + (elem.id === selectedElementId ? ' selected' : '');
            li.dataset.id = elem.id;
            li.innerHTML = `
                <span class="element-tag">&lt;${escapeHtml(elem.tag.split('.').pop())}&gt;</span>
                <span class="element-class">${escapeHtml(elem.class.split('.').pop())}</span>
                <span class="element-text">${escapeHtml(elem.text || '')}</span>
            `;
            li.addEventListener('click', () => selectElement(elem.id, li));
            elementList.appendChild(li);
        });
        elementList.style.display = 'block';
        const placeholder = elementsContainer.querySelector('.placeholder-box');
        if (placeholder) placeholder.style.display = 'none';
    }

    async function selectElement(elemId, liElem) {
        selectedElementId = elemId;
        document.querySelectorAll('.element-item.selected').forEach(el => el.classList.remove('selected'));
        if (liElem) liElem.classList.add('selected');
        try {
            const resp = await fetch('/api/elements/' + elemId);
            const data = await resp.json();
            if (data.success) {
                const elem = extractElement(data);
                if (!elem) throw new Error('元素详情响应缺少 element 字段');
                showElementDetail(elem);
                highlightElement(elem);
            }
        } catch (err) {
            console.error('获取元素详情失败', err);
        }
    }

    async function highlightElement(elem) {
        if (!elem.bounds || elem.bounds.length !== 4) return;
        drawHighlightBox(elem.bounds);
    }

    function drawHighlightBox(bounds) {
        if (highlightBox) { highlightBox.remove(); highlightBox = null; }
        if (!screenshotImg.naturalWidth || !screenshotImg.naturalHeight) {
            screenshotImg.addEventListener('load', () => drawHighlightBox(bounds), { once: true });
            return;
        }
        const imgRect = screenshotImg.getBoundingClientRect();
        const containerRect = screenshotContainer.getBoundingClientRect();
        if (imgRect.width <= 0 || imgRect.height <= 0) return;
        const scaleX = imgRect.width / screenshotImg.naturalWidth;
        const scaleY = imgRect.height / screenshotImg.naturalHeight;
        const imgOffsetX = imgRect.left - containerRect.left;
        const imgOffsetY = imgRect.top - containerRect.top;
        const [x1, y1, x2, y2] = bounds;
        const left = imgOffsetX + (x1 * scaleX);
        const top = imgOffsetY + (y1 * scaleY);
        const width = (x2 - x1) * scaleX;
        const height = (y2 - y1) * scaleY;
        highlightBox = document.createElement('div');
        highlightBox.style.cssText = `
            position: absolute; left: ${left}px; top: ${top}px;
            width: ${width}px; height: ${height}px;
            border: 5px solid #FF0000; background-color: rgba(255,0,0,0.3);
            box-shadow: 0 0 15px 3px rgba(255,0,0,0.8);
            pointer-events: none; z-index: 10; box-sizing: border-box;
        `;
        screenshotContainer.style.position = 'relative';
        screenshotContainer.appendChild(highlightBox);
        const placeholder = screenshotContainer.querySelector('.placeholder-box');
        if (placeholder) placeholder.style.display = 'none';
    }

    async function clearHighlight() {
        if (highlightBox) { highlightBox.remove(); highlightBox = null; }
    }

    async function locateByScreenshotClick(clickEvent) {
        if (!screenshotImg.naturalWidth || !screenshotImg.naturalHeight) return;
        if (!currentElements.length) {
            await loadElements();
            if (!currentElements.length) return;
        }
        const imgRect = screenshotImg.getBoundingClientRect();
        const scaleX = screenshotImg.naturalWidth / imgRect.width;
        const scaleY = screenshotImg.naturalHeight / imgRect.height;
        const clickX = clickEvent.clientX - imgRect.left;
        const clickY = clickEvent.clientY - imgRect.top;
        const origX = Math.round(clickX * scaleX);
        const origY = Math.round(clickY * scaleY);
        try {
            const resp = await fetch('/api/elements/locate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x: origX, y: origY })
            });
            const data = await resp.json();
            if (data.success) {
                const elem = extractElement(data);
                if (!elem) throw new Error('坐标反查响应缺少 element 字段');
                const liElem = elementList.querySelector(`[data-id="${elem.id}"]`);
                if (liElem) {
                    liElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    selectElement(elem.id, liElem);
                } else {
                    showElementDetail(elem);
                    highlightElement(elem);
                }
            }
        } catch (err) {
            console.error('坐标反查失败', err);
        }
    }

    screenshotImg.addEventListener('click', locateByScreenshotClick);

    function showElementDetail(elem) {
        currentDetailElement = elem;
        const content = document.getElementById('detail-content');
        content.innerHTML = `
            <div class="detail-row"><span class="detail-label">tag</span><span class="detail-value">${escapeHtml(elem.tag)}</span></div>
            <div class="detail-row"><span class="detail-label">text</span><span class="detail-value">${escapeHtml(elem.text || '')}</span></div>
            <div class="detail-row"><span class="detail-label">resource-id</span><span class="detail-value">${escapeHtml(elem.resource_id || '')}</span></div>
            <div class="detail-row"><span class="detail-label">content-desc</span><span class="detail-value">${escapeHtml(elem.content_desc || '')}</span></div>
            <div class="detail-row"><span class="detail-label">package</span><span class="detail-value">${escapeHtml(elem.package || '')}</span></div>
            <div class="detail-row"><span class="detail-label">bounds</span><span class="detail-value">[${(elem.bounds || []).join(', ')}]</span></div>
            <div class="detail-row"><span class="detail-label">clickable</span><span class="detail-value">${elem.clickable}</span></div>
            <div class="detail-row"><span class="detail-label">enabled</span><span class="detail-value">${elem.enabled}</span></div>
        `;
        document.getElementById('locator-xpath').value = elem.xpath || '';
        document.getElementById('locator-id').value = elem.resource_id || '';
        document.getElementById('locator-content-desc').value = elem.content_desc || '';
        detailPanel.style.display = 'block';
    }

    btnRefreshElements.addEventListener('click', loadSnapshot);

    btnCloseDetail.addEventListener('click', () => {
        detailPanel.style.display = 'none';
        document.querySelectorAll('.element-item.selected').forEach(el => el.classList.remove('selected'));
        clearHighlight();
        currentDetailElement = null;
    });

    document.addEventListener('click', async (e) => {
        if (e.target.classList.contains('btn-copy')) {
            const targetId = e.target.dataset.target;
            const input = document.getElementById(targetId);
            if (input) {
                try {
                    await navigator.clipboard.writeText(input.value);
                    const oldText = e.target.textContent;
                    e.target.textContent = '已复制';
                    setTimeout(() => e.target.textContent = oldText, 1200);
                } catch (err) {
                    console.error('复制失败', err);
                }
            }
        }
    });

    // ===== 发送到脚本编排 =====
    document.getElementById('btn-send-to-design').addEventListener('click', async () => {
        if (!currentDetailElement) {
            alert('请先选择一个元素');
            return;
        }
        try {
            const resp = await fetch('/api/script/elements', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentDetailElement)
            });
            const data = await resp.json();
            if (data.success) {
                alert(data.message || '已发送到脚本编排');
                loadDesignAll();
            } else {
                alert(data.message || '发送失败');
            }
        } catch (err) {
            console.error('发送到编排失败', err);
            alert('发送请求出错');
        }
    });

    // ===== 自动刷新 =====
    let autoRefreshTimer = null;
    let isAutoRefreshing = false;

    elementList.addEventListener('click', (e) => {
        const li = e.target.closest('.element-item');
        if (li) selectedElementId = li.dataset.id;
    });

    btnCloseDetail.addEventListener('click', () => { selectedElementId = null; });

    function startAutoRefresh() {
        if (isAutoRefreshing) return;
        isAutoRefreshing = true;
        autoRefreshInterval.disabled = false;
        // 递归 setTimeout：上一轮完成后再等 interval 发下一轮，避免慢设备上请求堆积
        const tick = async () => {
            if (!isAutoRefreshing) return;
            try {
                await refreshSilent();
                if (selectedElementId) {
                    const liElem = elementList.querySelector(`[data-id="${selectedElementId}"]`);
                    if (liElem) {
                        document.querySelectorAll('.element-item.selected').forEach(el => el.classList.remove('selected'));
                        liElem.classList.add('selected');
                        try {
                            const resp = await fetch('/api/elements/' + selectedElementId);
                            const data = await resp.json();
                            if (data.success) {
                                const elem = extractElement(data);
                                if (elem) {
                                    showElementDetail(elem);
                                    drawHighlightBox(elem.bounds);
                                }
                            }
                        } catch (e) { }
                    } else {
                        clearHighlight();
                        detailPanel.style.display = 'none';
                        selectedElementId = null;
                    }
                }
            } catch (err) {
                console.error('自动刷新失败', err);
            } finally {
                if (isAutoRefreshing) {
                    const interval = parseInt(autoRefreshInterval.value, 10) || 2000;
                    autoRefreshTimer = setTimeout(tick, interval);
                }
            }
        };
        autoRefreshTimer = setTimeout(tick, 0);
    }

    function stopAutoRefresh() {
        if (autoRefreshTimer) { clearTimeout(autoRefreshTimer); autoRefreshTimer = null; }
        isAutoRefreshing = false;
        autoRefreshInterval.disabled = true;
    }

    async function loadScreenshotSilent() {
        try {
            const resp = await fetch('/api/screenshot?t=' + Date.now());
            if (!resp.ok) return;
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const oldPrevUrl = screenshotImg.dataset.prevUrl;
            screenshotImg.src = url;
            screenshotImg.dataset.prevUrl = url;
            screenshotImg.onload = () => {
                if (oldPrevUrl && oldPrevUrl !== url) URL.revokeObjectURL(oldPrevUrl);
                if (currentDetailElement?.bounds) drawHighlightBox(currentDetailElement.bounds);
            };
            screenshotImg.style.display = 'block';
            const placeholder = screenshotContainer.querySelector('.placeholder-box');
            if (placeholder) placeholder.style.display = 'none';
        } catch (err) { }
    }

    async function loadElementsSilent() {
        try {
            const resp = await fetch('/api/elements/refresh', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                renderElementList(data.elements);
                if (selectedElementId) {
                    const li = elementList.querySelector(`[data-id="${selectedElementId}"]`);
                    if (li) li.classList.add('selected');
                }
            }
        } catch (err) { }
    }

    autoRefreshToggle.addEventListener('change', () => {
        if (autoRefreshToggle.checked) {
            loadSnapshot().then(() => startAutoRefresh());
        } else {
            stopAutoRefresh();
        }
    });

    autoRefreshInterval.addEventListener('change', () => {
        if (isAutoRefreshing) { stopAutoRefresh(); startAutoRefresh(); }
    });

    // ==================== Tab2: 脚本编排 ====================

    let designElements = [];
    let allSteps = [];
    let editingStepId = null;

    const designElemList = document.getElementById('design-elem-list');
    const designElemsContainer = document.getElementById('design-elems-container');
    const stepElementSelect = document.getElementById('step-element-select');
    const stepActionSelect = document.getElementById('step-action-select');
    const stepList = document.getElementById('step-list');
    const stepsContainer = document.getElementById('steps-container');

    async function loadDesignAll() {
        try {
            const result = await apiFetch('GET', '/api/script/design');
            if (result.success) {
                designElements = result.elements || [];
                allSteps = result.steps || [];
                renderDesignElements();
                updateElementDropdown();
                renderSteps();
                updateTab2Badge();
            }
        } catch (err) {
            console.error('加载设计数据失败', err);
        }
    }

    function renderDesignElements() {
        if (designElements.length === 0) {
            designElemList.style.display = 'none';
            const ph = designElemsContainer.querySelector('.placeholder-box');
            if (ph) ph.style.display = 'block';
            return;
        }
        const ph = designElemsContainer.querySelector('.placeholder-box');
        if (ph) ph.style.display = 'none';
        designElemList.innerHTML = '';
        designElemList.style.display = 'block';
        designElements.forEach(elem => {
            const li = document.createElement('li');
            li.className = 'element-item';
            const tagShort = escapeHtml((elem.tag || '').split('.').pop());
            const text = escapeHtml(elem.text || elem.resource_id || '');
            li.innerHTML = `
                <span class="element-tag">&lt;${tagShort}&gt;</span>
                <span class="element-text">${text}</span>
                <button class="btn btn-small btn-danger" data-action="delete-elem" data-id="${elem.design_elem_id}" style="float:right;padding:2px 6px;font-size:10px;">删除</button>
            `;
            designElemList.appendChild(li);
        });
    }

    function updateElementDropdown() {
        const currentValue = stepElementSelect.value;
        stepElementSelect.innerHTML = '<option value="">-- 无元素（wait/back/screenshot） --</option>';
        designElements.forEach(elem => {
            const option = document.createElement('option');
            option.value = elem.design_elem_id;
            const tag = (elem.tag || '').split('.').pop();
            const label = elem.text || elem.resource_id || elem.design_elem_id;
            option.textContent = `<${tag}> ${label}`;
            stepElementSelect.appendChild(option);
        });
        if (currentValue) {
            stepElementSelect.value = currentValue;
        }
    }

    function updateActionParams() {
        const action = stepActionSelect.value;
        document.getElementById('param-input-group').style.display = action === 'input' ? 'block' : 'none';
        document.getElementById('param-swipe-group').style.display = action === 'swipe' ? 'block' : 'none';
        document.getElementById('param-presshold-group').style.display = action === 'press_hold' ? 'block' : 'none';
        document.getElementById('param-wait-group').style.display = action === 'wait' ? 'block' : 'none';
    }

    stepActionSelect.addEventListener('change', updateActionParams);

    function getActionParams() {
        const action = stepActionSelect.value;
        switch (action) {
            case 'input':
                return { value: document.getElementById('param-input-value').value };
            case 'swipe':
                return { direction: document.getElementById('param-swipe-direction').value };
            case 'press_hold':
                return {
                    direction: document.getElementById('param-presshold-direction').value,
                    hold: parseFloat(document.getElementById('param-presshold-hold').value) || 1,
                    strength: parseFloat(document.getElementById('param-presshold-strength').value) || 0.8
                };
            case 'wait':
                return { timeout: parseInt(document.getElementById('param-wait-timeout').value, 10) || 3 };
            default:
                return {};
        }
    }

    function getSelectedElement() {
        const elemId = stepElementSelect.value;
        if (!elemId) return null;
        return designElements.find(e => e.design_elem_id === elemId) || null;
    }

    document.getElementById('btn-add-step').addEventListener('click', async () => {
        const action = stepActionSelect.value;
        const actionParams = getActionParams();
        const description = document.getElementById('step-description').value;
        const element = getSelectedElement();
        try {
            const result = await apiFetch('POST', '/api/script/steps', {
                element, action, action_params: actionParams, description
            });
            if (result.success) {
                document.getElementById('step-description').value = '';
                document.getElementById('param-input-value').value = '';
                await loadDesignAll();
            } else {
                alert(result.message || '添加失败');
            }
        } catch (err) {
            console.error('添加步骤失败', err);
            alert('添加步骤请求出错');
        }
    });

    function renderSteps() {
        if (allSteps.length === 0) {
            stepList.style.display = 'none';
            const ph = stepsContainer.querySelector('.placeholder-box');
            if (ph) ph.style.display = 'block';
            return;
        }
        const ph = stepsContainer.querySelector('.placeholder-box');
        if (ph) ph.style.display = 'none';
        stepList.innerHTML = '';
        stepList.style.display = 'block';
        allSteps.forEach(step => {
            const li = document.createElement('li');
            li.className = 'step-item' + (step.step_id === editingStepId ? ' editing' : '');
            const elem = step.element;
            let elemInfo = '无元素';
            if (elem) {
                const tag = (elem.tag || '').split('.').pop();
                const label = elem.text || elem.resource_id || '';
                elemInfo = `<${tag}> ${label}`;
            }
            let paramInfo = '';
            const ap = step.action_params || {};
            if (step.action === 'input') paramInfo = `: "${ap.value || ''}"`;
            else if (step.action === 'swipe') paramInfo = `: ${ap.direction || ''}`;
            else if (step.action === 'press_hold') paramInfo = `: ${ap.direction || ''} ${ap.hold || 0}s`;
            else if (step.action === 'wait') paramInfo = `: ${ap.timeout || 0}s`;
            li.innerHTML = `
                <div class="step-header">
                    <span class="step-order">${step.step_order}</span>
                    <span class="step-action-badge ${escapeHtml(step.action)}">${escapeHtml(step.action)}</span>
                </div>
                <div class="step-body">${escapeHtml(elemInfo)}${escapeHtml(paramInfo)}</div>
                ${step.description ? `<div class="step-desc">${escapeHtml(step.description)}</div>` : ''}
                <div class="step-controls">
                    <button class="btn btn-small" data-action="edit" data-id="${step.step_id}">编辑</button>
                    <button class="btn btn-small" data-action="up" data-id="${step.step_id}">上移</button>
                    <button class="btn btn-small" data-action="down" data-id="${step.step_id}">下移</button>
                    <button class="btn btn-small btn-danger" data-action="delete" data-id="${step.step_id}">删除</button>
                </div>
            `;
            stepList.appendChild(li);
        });
    }

    stepList.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const stepId = btn.dataset.id;

        if (action === 'edit') {
            editStep(stepId);
        } else if (action === 'delete') {
            if (confirm('确认删除此步骤？')) {
                await apiFetch('DELETE', `/api/script/steps/${stepId}`);
                if (editingStepId === stepId) cancelEdit();
                await loadDesignAll();
            }
        } else if (action === 'up' || action === 'down') {
            const currentIndex = allSteps.findIndex(s => s.step_id === stepId);
            const targetIndex = action === 'up' ? currentIndex - 1 : currentIndex + 1;
            if (targetIndex < 0 || targetIndex >= allSteps.length) return;
            const newOrder = [...allSteps];
            const tmp = newOrder[currentIndex];
            newOrder[currentIndex] = newOrder[targetIndex];
            newOrder[targetIndex] = tmp;
            const stepIds = newOrder.map(s => s.step_id);
            await apiFetch('POST', '/api/script/steps/reorder', { step_ids: stepIds });
            await loadDesignAll();
        }
    });

    function editStep(stepId) {
        const step = allSteps.find(s => s.step_id === stepId);
        if (!step) return;
        editingStepId = stepId;
        if (step.element && step.element.design_elem_id) {
            stepElementSelect.value = step.element.design_elem_id;
        } else {
            stepElementSelect.value = '';
        }
        stepActionSelect.value = step.action;
        updateActionParams();
        const ap = step.action_params || {};
        if (step.action === 'input') {
            document.getElementById('param-input-value').value = ap.value || '';
        } else if (step.action === 'swipe') {
            document.getElementById('param-swipe-direction').value = ap.direction || 'up';
        } else if (step.action === 'press_hold') {
            document.getElementById('param-presshold-direction').value = ap.direction || 'up';
            document.getElementById('param-presshold-hold').value = ap.hold || 1;
            document.getElementById('param-presshold-strength').value = ap.strength || 0.8;
        } else if (step.action === 'wait') {
            document.getElementById('param-wait-timeout').value = ap.timeout || 3;
        }
        document.getElementById('step-description').value = step.description || '';
        document.getElementById('btn-add-step').style.display = 'none';
        document.getElementById('btn-update-step').style.display = 'inline-block';
        document.getElementById('btn-cancel-edit').style.display = 'inline-block';
        renderSteps();
    }

    function cancelEdit() {
        editingStepId = null;
        document.getElementById('step-description').value = '';
        document.getElementById('param-input-value').value = '';
        stepElementSelect.value = '';
        stepActionSelect.value = 'click';
        updateActionParams();
        document.getElementById('btn-add-step').style.display = 'inline-block';
        document.getElementById('btn-update-step').style.display = 'none';
        document.getElementById('btn-cancel-edit').style.display = 'none';
        renderSteps();
    }

    document.getElementById('btn-cancel-edit').addEventListener('click', cancelEdit);

    document.getElementById('btn-update-step').addEventListener('click', async () => {
        if (!editingStepId) return;
        const action = stepActionSelect.value;
        const actionParams = getActionParams();
        const description = document.getElementById('step-description').value;
        const element = getSelectedElement();
        try {
            const result = await apiFetch('PUT', `/api/script/steps/${editingStepId}`, {
                element, action, action_params: actionParams, description
            });
            if (result.success) {
                cancelEdit();
                await loadDesignAll();
            } else {
                alert(result.message || '修改失败');
            }
        } catch (err) {
            console.error('修改步骤失败', err);
            alert('修改步骤请求出错');
        }
    });

    designElemList.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action="delete-elem"]');
        if (!btn) return;
        const elemId = btn.dataset.id;
        if (confirm('确认删除此元素？关联的步骤也会被移除。')) {
            await apiFetch('DELETE', `/api/script/elements/${elemId}`);
            await loadDesignAll();
        }
    });

    document.getElementById('btn-design-refresh-elems').addEventListener('click', loadDesignAll);
    document.getElementById('btn-design-refresh-steps').addEventListener('click', loadDesignAll);

    document.getElementById('btn-design-clear-elems').addEventListener('click', async () => {
        if (confirm('确认清空所有设计元素和步骤？')) {
            await apiFetch('POST', '/api/script/clear');
            cancelEdit();
            await loadDesignAll();
        }
    });

    document.getElementById('btn-clear-design').addEventListener('click', async () => {
        if (confirm('确认清空所有设计数据？')) {
            await apiFetch('POST', '/api/script/clear');
            cancelEdit();
            await loadDesignAll();
        }
    });

    document.getElementById('btn-save-case').addEventListener('click', async () => {
        const name = document.getElementById('case-name-input').value.trim();
        if (!name) { alert('请输入用例名称'); return; }
        try {
            const result = await apiFetch('POST', '/api/script/save', { name });
            if (result.success) {
                alert(result.message || '保存成功');
            } else {
                alert(result.message || '保存失败');
            }
        } catch (err) {
            console.error('保存用例失败', err);
            alert('保存用例请求出错');
        }
    });

    document.getElementById('btn-load-case').addEventListener('click', async () => {
        try {
            const result = await apiFetch('GET', '/api/script/cases');
            const container = document.getElementById('case-list-container');
            if (result.success && result.cases && result.cases.length > 0) {
                container.innerHTML = '';
                result.cases.forEach(c => {
                    const card = document.createElement('div');
                    card.className = 'case-card';
                    card.innerHTML = `
                        <div class="case-card-name">${escapeHtml(c.name)}</div>
                        <div class="case-card-info">${c.step_count || 0} 步骤 / ${c.element_count || 0} 元素 / ${escapeHtml(c.saved_at || '')}</div>
                        <button class="btn btn-small btn-danger case-delete-btn" data-name="${escapeHtml(c.name)}" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);padding:2px 8px;font-size:11px;">删除</button>
                    `;
                    card.style.position = 'relative';
                    // 删除按钮：阻止冒泡，避免触发卡片 click 加载
                    const delBtn = card.querySelector('.case-delete-btn');
                    delBtn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const caseName = delBtn.dataset.name;
                        if (!confirm(`确认删除用例「${caseName}」？此操作不可恢复。`)) return;
                        try {
                            const delRes = await apiFetch('DELETE', `/api/script/cases/${encodeURIComponent(caseName)}`);
                            if (delRes.success) {
                                card.remove();
                                alert(delRes.message || '已删除');
                                // 若列表清空，展示占位
                                if (container.children.length === 0) {
                                    container.innerHTML = '<div class="placeholder-box"><p>暂无已保存的用例</p></div>';
                                }
                            } else {
                                alert(delRes.message || '删除失败');
                            }
                        } catch (err) {
                            console.error('删除用例失败', err);
                            alert('删除用例请求出错');
                        }
                    });
                    card.addEventListener('click', async () => {
                        try {
                            const loadResult = await apiFetch('GET', `/api/script/load/${c.name}`);
                            if (loadResult.success) {
                                document.getElementById('case-modal').style.display = 'none';
                                cancelEdit();
                                await loadDesignAll();
                                alert('用例已加载: ' + c.name);
                            } else {
                                alert(loadResult.message || '加载失败');
                            }
                        } catch (err) {
                            alert('加载请求出错');
                        }
                    });
                    container.appendChild(card);
                });
            } else {
                container.innerHTML = '<div class="placeholder-box"><p>暂无已保存的用例</p></div>';
            }
            document.getElementById('case-modal').style.display = 'flex';
        } catch (err) {
            console.error('获取用例列表失败', err);
            alert('获取用例列表请求出错');
        }
    });

    document.getElementById('btn-close-case-modal').addEventListener('click', () => {
        document.getElementById('case-modal').style.display = 'none';
    });

    document.getElementById('case-modal').addEventListener('click', (e) => {
        if (e.target.id === 'case-modal') {
            document.getElementById('case-modal').style.display = 'none';
        }
    });

    function updateTab2Badge() {
        const badge = document.getElementById('tab2-badge');
        if (allSteps.length > 0) {
            badge.textContent = allSteps.length;
            badge.style.display = 'inline-flex';
        } else {
            badge.style.display = 'none';
        }
    }

    // ==================== Tab3: 脚本生成与执行 ====================

    async function refreshGenPreview() {
        try {
            const result = await apiFetch('GET', '/api/script/gen/preview');
            if (result.success) {
                document.getElementById('gen-placeholder').style.display = 'none';
                document.getElementById('gen-code-preview').textContent = result.code;
                document.getElementById('gen-code-preview').style.display = 'block';
                document.getElementById('btn-gen-execute').disabled = false;
            } else {
                const ph = document.getElementById('gen-placeholder');
                ph.style.display = 'flex';
                ph.innerHTML = `
                    <p style="font-size:48px;margin-bottom:16px;">&#9881;</p>
                    <p>${escapeHtml(result.message || '暂无脚本')}</p>
                    <p class="placeholder-hint">请先在「脚本编排」中完成测试步骤设计</p>
                `;
                document.getElementById('gen-code-preview').style.display = 'none';
                document.getElementById('btn-gen-execute').disabled = true;
            }
        } catch (err) {
            console.error('刷新预览失败', err);
        }
    }

    document.getElementById('btn-gen-refresh').addEventListener('click', refreshGenPreview);

    document.getElementById('btn-gen-download').addEventListener('click', () => {
        window.open('/api/script/gen/download', '_blank');
    });

    document.getElementById('btn-gen-execute').addEventListener('click', async () => {
        const btnExecute = document.getElementById('btn-gen-execute');
        const originalText = btnExecute.textContent;
        btnExecute.disabled = true;
        btnExecute.textContent = '执行中...';

        const execPanel = document.getElementById('exec-results-panel');
        const execContainer = document.getElementById('exec-results-container');
        const execSummary = document.getElementById('exec-summary');
        execPanel.style.display = 'flex';
        execContainer.innerHTML = '<div style="text-align:center;color:#9e9e9e;padding:20px;">正在执行测试步骤...</div>';
        execSummary.textContent = '';
        execSummary.className = 'exec-summary';

        try {
            const result = await apiFetch('POST', '/api/script/gen/execute');
            renderExecResults(result);
        } catch (err) {
            console.error('执行失败', err);
            execContainer.innerHTML = '<div style="color:#e74c3c;padding:10px;">执行请求出错</div>';
            execSummary.textContent = '执行失败';
            execSummary.className = 'exec-summary fail';
        } finally {
            btnExecute.disabled = false;
            btnExecute.textContent = originalText;
        }
    });

    function renderExecResults(result) {
        const execContainer = document.getElementById('exec-results-container');
        const execSummary = document.getElementById('exec-summary');

        if (!result.results || result.results.length === 0) {
            execContainer.innerHTML = '<div style="color:#9e9e9e;padding:10px;">' + escapeHtml(result.message || '无执行结果') + '</div>';
            execSummary.textContent = result.message || '无结果';
            execSummary.className = 'exec-summary fail';
            return;
        }

        execContainer.innerHTML = '';
        result.results.forEach(step => {
            const item = document.createElement('div');
            item.className = 'exec-step-item';
            const icon = step.success ? '\u2713' : '\u2717';
            const iconClass = step.success ? 'pass' : 'fail';
            const msgClass = step.success ? '' : 'fail';
            item.innerHTML = `
                <div class="exec-step-icon ${iconClass}">${icon}</div>
                <div class="exec-step-body">
                    <div class="exec-step-msg ${msgClass}">${escapeHtml(step.message)}</div>
                </div>
            `;
            execContainer.appendChild(item);
        });

        const passed = result.results.filter(r => r.success).length;
        const total = result.total_steps;
        if (result.success) {
            execSummary.textContent = '全部通过 (' + passed + '/' + total + ') - ' + (result.executed_at || '');
            execSummary.className = 'exec-summary pass';
        } else {
            execSummary.textContent = '失败 (' + passed + '/' + total + ' 通过) - ' + (result.executed_at || '');
            execSummary.className = 'exec-summary fail';
        }
    }

    // ==================== 初始化 ====================

    fetchDeviceStatus();
    loadDesignAll();
});
