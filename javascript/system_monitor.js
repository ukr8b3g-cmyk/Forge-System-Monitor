(() => {
    'use strict';

    const prefix = 'forge_system_monitor_';
    const fields = ['CPU', 'RAM', 'GPU', 'VRAM', 'GPU Temperature'];
    const gpuFields = new Set(fields.slice(2));
    const corners = { 'Bottom right': 'br', 'Bottom left': 'bl', 'Top right': 'tr', 'Top left': 'tl' };
    const periods = { '1 second': 1000, '2 seconds': 2000, '5 seconds': 5000 };
    const labels = {
        en: { title: 'System Monitor', temperature: 'GPU Temperature', unavailable: 'System data unavailable',
            noGpu: 'GPU data unavailable', chooseGpu: 'Select a GPU in Settings.' },
        ja: { title: 'システムモニター', temperature: 'GPU 温度', unavailable: '計測データを取得できません',
            noGpu: 'GPU の計測データを取得できません', chooseGpu: '設定で監視する GPU を選んでください。' },
    };
    const gibibyte = 1024 ** 3;
    let view, config, timer, request;
    let readings = {};
    let failed = false;
    let updatePending = false;

    function createView() {
        const host = document.createElement('section');
        host.id = 'forge-system-monitor';
        const shadow = host.attachShadow({ mode: 'open' });
        shadow.innerHTML = `
            <style>
                :host { display: block; box-sizing: border-box; width: 100%; min-width: 0; }
                :host([data-corner]) { position: fixed; z-index: 20; width: min(17rem, calc(100vw - 1.5rem)); pointer-events: none; }
                :host([data-corner^="b"]) { bottom: .75rem; }
                :host([data-corner^="t"]) { top: .75rem; }
                :host([data-corner$="r"]) { right: .75rem; }
                :host([data-corner$="l"]) { left: .75rem; }
                [hidden] { display: none !important; }
                .monitor {
                    box-sizing: border-box;
                    padding: .55rem .65rem;
                    border: 1px solid var(--block-border-color, var(--border-color-primary, #708099));
                    border-radius: var(--block-radius, .4rem);
                    color: var(--body-text-color, CanvasText);
                    background: var(--block-background-fill, var(--background-fill-primary, Canvas));
                    font-family: inherit;
                    font-size: var(--body-text-size, .875rem);
                    line-height: 1.35;
                }
                :host([data-corner]) .monitor { box-shadow: 0 .2rem .75rem rgb(0 0 0 / 18%); }
                .title { font-weight: 600; cursor: pointer; }
                .monitor[open] > .title { margin-bottom: .35rem; }
                :host([data-corner]) .title { pointer-events: auto; }
                .rows { display: grid; gap: .3rem; }
                .reading { display: flex; justify-content: space-between; gap: .2rem .4rem; flex-wrap: wrap; }
                .value { font-variant-numeric: tabular-nums; white-space: nowrap; }
                progress { display: block; width: 100%; height: .25rem; appearance: none; border: 0;
                    margin-top: .15rem; border-radius: .2rem; overflow: hidden; accent-color: var(--fsm-fill);
                    background: var(--background-fill-secondary, color-mix(in srgb, CanvasText 16%, Canvas));
                    --fsm-fill: #2d9565; }
                .gpu progress { --fsm-fill: #3484cc; }
                progress::-webkit-progress-bar { background: transparent; }
                progress::-webkit-progress-value { background: var(--fsm-fill); }
                progress::-moz-progress-bar { background: var(--fsm-fill); }
                .detail { margin-top: .3rem;
                    font-size: .82em; overflow-wrap: anywhere; }
            </style>
            <details class="monitor" open>
                <summary class="title"></summary>
                <div class="rows"></div>
                <div class="detail"></div>
            </details>`;
        const root = shadow.querySelector('.rows');
        const rows = new Map();
        for (const field of fields) {
            const row = document.createElement('div');
            if (gpuFields.has(field)) row.className = 'gpu';
            const reading = document.createElement('div');
            reading.className = 'reading';
            const label = document.createElement('span');
            const value = document.createElement('span');
            value.className = 'value';
            reading.append(label, value);
            row.append(reading);
            let progress;
            if (field !== 'GPU Temperature') {
                progress = document.createElement('progress');
                progress.max = 100;
                row.append(progress);
            }
            rows.set(field, { row, label, value, progress });
            root.append(row);
        }
        const details = shadow.querySelector('.monitor');
        details.addEventListener('toggle', () => {
            if (details.open) schedulePoll(0);
            else stopPolling();
        });
        return { host, details, title: shadow.querySelector('.title'), detail: shadow.querySelector('.detail'), rows };
    }

    function readOptions() {
        const saved = typeof opts === 'object' && opts ? opts : {};
        const get = (key) => saved[prefix + key];
        const savedFields = get('metrics');
        const selected = Array.isArray(savedFields) ? fields.filter((field) => savedFields.includes(field)) : fields;
        const floating = get('position') === 'Floating';
        const corner = corners[get('corner')] || 'br';
        const selection = get('gpu') || 'Auto';
        const interval = periods[get('interval')] || 2000;
        const language = get('language');
        const japanese = /^(?:ja(?:$|[-_ (])|japanese(?:$|[-_ (])|日本語)/i.test(String(saved.localization || '').trim());
        const locale = language === 'Japanese' || (language !== 'English' && japanese) ? 'ja' : 'en';
        return { enabled: get('enabled') === true && selected.length > 0, selected, floating, corner, selection,
            interval, locale, requestKey: JSON.stringify([selected, selection, interval]) };
    }

    function formatPercent(value) {
        return Number.isFinite(value) ? [Math.round(value) + '%', value] : ['—', null];
    }

    function formatMemory(memory) {
        if (!memory || !Number.isFinite(memory.used) || !Number.isFinite(memory.total) || memory.total <= 0) {
            return ['—', null];
        }
        const percent = 100 * memory.used / memory.total;
        return [(memory.used / gibibyte).toFixed(1) + ' / ' + (memory.total / gibibyte).toFixed(1) +
            ' GiB · ' + Math.round(percent) + '%', percent];
    }

    function display() {
        if (!view || !config) return;
        const copy = labels[config.locale];
        const gpu = readings.gpu || {};
        view.host.lang = config.locale;
        view.host.setAttribute('aria-label', copy.title);
        view.title.textContent = copy.title;
        const values = [formatPercent(readings.cpu), formatMemory(readings.ram), formatPercent(gpu.usage),
            formatMemory(gpu.vram), [Number.isFinite(gpu.temperature) ? Math.round(gpu.temperature) + ' °C' : '—', null]];
        for (const [index, field] of fields.entries()) {
            const { row, label, value, progress } = view.rows.get(field);
            const [printed, percent] = values[index];
            const caption = field === 'GPU Temperature' ? copy.temperature : field;
            row.hidden = !config.selected.includes(field);
            label.textContent = caption;
            value.textContent = printed;
            if (progress) {
                progress.hidden = percent === null;
                progress.value = percent === null ? 0 : Math.min(100, Math.max(0, percent));
                progress.setAttribute('aria-label', caption);
            }
        }
        let detail = '';
        if (failed) detail = copy.unavailable;
        else if (config.selected.some((field) => gpuFields.has(field))) {
            detail = gpu.name || (readings.gpu_status === 'select' ? copy.chooseGpu :
                readings.gpu_status === 'unavailable' ? copy.noGpu : '');
        }
        view.detail.hidden = !detail;
        view.detail.textContent = detail;
    }

    function updateCornerOption(scope) {
        const row = scope.getElementById('setting_' + prefix + 'corner');
        const position = scope.getElementById('setting_' + prefix + 'position');
        if (!row || !position) return;
        const saved = typeof opts === 'object' && opts ? opts[prefix + 'position'] : null;
        const visible = position.querySelector('input')?.value || saved;
        const show = visible === 'Floating' || visible === 'フローティング';
        if (row.dataset.fsmVisible !== String(show)) row.dataset.fsmVisible = String(show);
    }

    function placementTarget(scope, tabName, floating) {
        if (floating) return { inside: scope.getElementById('tabs')?.parentElement };
        const actions = scope.getElementById(tabName + '_actions_column');
        if (actions?.getClientRects().length) {
            const tags = actions.querySelector(':scope > .easy_prompt_selector_container');
            return tags ? { after: tags } : { inside: actions };
        }
        // The compact prompt layout can move Generate out of the action column.
        const generate = scope.getElementById(tabName + '_generate_box');
        return generate?.getClientRects().length ? { after: generate } : {};
    }

    function mount(target, cfg) {
        if (!view) view = createView();
        const { host } = view;
        if (cfg.floating && host.dataset.corner !== cfg.corner) host.dataset.corner = cfg.corner;
        if (!cfg.floating && host.hasAttribute('data-corner')) host.removeAttribute('data-corner');
        if (target.after && target.after.nextElementSibling !== host) target.after.after(host);
        if (target.inside && host.parentElement !== target.inside) target.inside.append(host);
    }

    function stopPolling() {
        if (timer) clearTimeout(timer);
        timer = null;
        request?.abort();
    }

    function schedulePoll(delay) {
        if (!config || !view?.details.open || request || timer) return;
        timer = setTimeout(poll, delay);
    }

    async function poll() {
        timer = null;
        if (!config || !view?.details.open || request) return;
        const key = config.requestKey;
        const controller = new AbortController();
        request = controller;
        const deadline = setTimeout(() => controller.abort('timeout'), 6000);
        try {
            const base = new URL(location.href);
            if (!base.pathname.endsWith('/')) base.pathname += '/';
            const response = await fetch(new URL('internal/forge-system-monitor', base), {
                cache: 'no-store', signal: controller.signal,
            });
            if (!response.ok) throw new Error('Monitor HTTP ' + response.status);
            const latest = await response.json();
            if (!controller.signal.aborted && config?.requestKey === key) {
                readings = latest;
                failed = false;
                display();
            }
        } catch (_) {
            if ((!controller.signal.aborted || controller.signal.reason === 'timeout') && config?.requestKey === key) {
                readings = {};
                failed = true;
                display();
            }
        } finally {
            clearTimeout(deadline);
            request = null;
            if (config) schedulePoll(controller.signal.aborted && controller.signal.reason !== 'timeout' ? 0 : config.interval);
        }
    }

    function reconcile() {
        updatePending = false;
        const scope = gradioApp();
        updateCornerOption(scope);
        const tab = get_uiCurrentTabContent()?.id;
        const name = tab === 'tab_txt2img' ? 'txt2img' : tab === 'tab_img2img' ? 'img2img' : null;
        const next = readOptions();
        const target = name && next.enabled && !document.hidden ? placementTarget(scope, name, next.floating) : {};
        if (!target.inside && !target.after) {
            if (config) stopPolling();
            config = null;
            view?.host.remove();
            return;
        }
        const sampleChanged = next.requestKey !== config?.requestKey;
        const visualChanged = sampleChanged || next.locale !== config?.locale;
        config = next;
        mount(target, next);
        if (sampleChanged) {
            stopPolling();
            readings = {};
            failed = false;
        }
        if (visualChanged) display();
        schedulePoll(0);
    }

    function scheduleReconcile() {
        if (updatePending) return;
        updatePending = true;
        requestAnimationFrame(reconcile);
    }

    onUiLoaded(scheduleReconcile);
    onUiTabChange(scheduleReconcile);
    onOptionsChanged(scheduleReconcile);
    onUiUpdate(scheduleReconcile);
    document.addEventListener('visibilitychange', () => {
        // Frames are throttled when the document becomes hidden.
        if (document.hidden) reconcile();
        else scheduleReconcile();
    });
    for (const event of ['change', 'input', 'click']) {
        document.addEventListener(event, (event) => {
            if (event.composedPath().some((node) => node.id === 'setting_' + prefix + 'position')) scheduleReconcile();
        });
    }
})();
