// window.sysai for the window in a browser (serve.js): Hermes is a script, the projects are real (lib/projects.js over
// /rpc), the rest answers with something plausible. ?scene=work (a conversation in the middle of a job, the pane with
// the project) | chat (the conversation alone) | empty (a new conversation) | boot (Hermes does not start).
(() => {
  const scene = new URLSearchParams(location.search).get('scene') || 'work';
  const listeners = {};
  const on = (ch) => (fn) => { (listeners[ch] = listeners[ch] || []).push(fn); return () => {}; };
  const emit = (ch, payload) => (listeners[ch] || []).forEach((fn) => fn(payload));
  const rpc = async (channel, ...args) => {
    const r = await fetch('/rpc', { method: 'POST', body: JSON.stringify({ channel, args }) }).then((x) => x.json());
    if (!r.ok) throw new Error(r.error);
    return r.value;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PROJECT = '/tmp/sysai-ui-demo/Элеватор Благовещенск';
  const ago = (m) => new Date(Date.now() - m * 60000).toISOString();
  const SESSIONS = [
    { sessionId: 's-work', title: 'Собрать проект элеватора по ТЗ и Э3', updatedAt: ago(2), cwd: PROJECT },
    { sessionId: 's-2', title: 'Разобрать пример проекта 2024 года', updatedAt: ago(90), cwd: PROJECT },
    { sessionId: 's-3', title: 'Почему не открывается окно 12 на панели', updatedAt: ago(60 * 26) },
    { sessionId: 's-4', title: 'Сверить перечень сигналов с Э3 лист 7', updatedAt: ago(60 * 24 * 3) },
    { sessionId: 's-5', title: 'Экспорт тегов OPC UA для панели', updatedAt: ago(60 * 24 * 9) },
  ];
  const text = (t) => ({ type: 'text', text: t });
  const out = (t) => [{ type: 'content', content: text(t) }];
  const MODEL = [{ id: 'model', name: 'Модель', type: 'select', currentValue: 'strong', options: [
    { value: 'strong', name: 'Claude Sonnet — сильная' }, { value: 'mid', name: 'GPT — средняя' }, { value: 'cheap', name: 'Kimi — быстрая' }] }];

  function script(sid) {
    const u = (update) => emit('acp:notification', { method: 'session/update', params: { sessionId: sid, update } });
    const tool = (id, title, rawInput, status, content, kind = 'other') => u({ sessionUpdate: 'tool_call', toolCallId: id, title, kind,
      status, rawInput, content: content ? out(content) : undefined });
    u({ sessionUpdate: 'user_message_chunk', content: text('Собери проект элеватора: в материалах ТЗ, схема Э3 и перечень механизмов. Контроллер M241, панель cMT. Иди по этапам.') });
    u({ sessionUpdate: 'agent_thought_chunk', content: text('Проект уже начат: материалы и решения закрыты, программа написана. Следующий этап — компиляция. Сначала прочитаю ход в pipeline.json.') });
    u({ sessionUpdate: 'plan', entries: [
      { content: 'Прочитать ход проекта и спецификацию', status: 'completed', priority: 'high' },
      { content: 'Собрать проект Machine Expert и скомпилировать', status: 'in_progress', priority: 'high' },
      { content: 'Проверить логику в симуляции', status: 'pending', priority: 'medium' },
      { content: 'Собрать экраны панели cMT3072X', status: 'pending', priority: 'medium' },
    ] });
    tool('t1', 'mcp__plc_kit__plc_stage_update: ' + PROJECT, { project_dir: PROJECT }, 'completed', '{"next": "build", "done": 3}');
    tool('t2', 'read_file: _work/spec/project.spec.json', { path: '_work/spec/project.spec.json' }, 'completed', '12 механизмов, 96 сигналов', 'read');
    tool('t3', 'mcp__plc_kit__plc_stage_update: ' + PROJECT, { project_dir: PROJECT, stage: 'build', state: 'work', note: 'Компилирую в Machine Expert' }, 'completed', 'ok');
    tool('t4', 'tool_call: mcp__plc_kit__plc_project_build', { name: 'mcp__plc_kit__plc_project_build', arguments: { project_dir: PROJECT } }, 'completed',
      'ОШИБКА (plc-kit/plc_project_build): канал DI.I7 привязан к двум сигналам (N3.belt, N4.speed)\n[SYSAI: сервер plc-kit работает и ответил — это ответ на ЭТОТ вызов, а не обрыв связи.]');
    u({ sessionUpdate: 'agent_message_chunk', content: text('Канал **DI.I7** оказался у двух сигналов — по Э3 лист 7 это датчик схода ленты нории N3, у N4 скорость на **DI.I8**. Исправил спецификацию и собираю снова.\n\n') });
    tool('t5', 'patch: _work/spec/project.spec.json', { path: '_work/spec/project.spec.json' }, 'completed', '', 'edit');
    tool('t6', 'mcp__plc_kit__plc_project_build: ' + PROJECT, { project_dir: PROJECT }, 'completed', 'Elevator.project собран: 12 FB, 96 каналов, OPC UA');
    tool('t7', 'mcp__machine_expert__me_build: plc/Elevator.project', { file: 'plc/Elevator.project' }, scene === 'work' ? 'in_progress' : 'completed',
      scene === 'work' ? null : '0 ошибок, 2 предупреждения');
    if (scene !== 'work') {
      u({ sessionUpdate: 'agent_message_chunk', content: text('Компиляция прошла: **0 ошибок**, 2 предупреждения (неиспользуемые переменные `GVL.tmp1`, `GVL.tmp2`).\n\n| Этап | Состояние |\n|---|---|\n| Программа ПЛК | готово |\n| Компиляция | готово |\n| Экраны | следующий |\n\nДальше — проверка в симуляции и экраны.') });
    }
    u({ sessionUpdate: 'usage_update', used: 48200, size: 200000 });
  }

  let gen = 0;
  window.sysai = {
    info: async () => ({ version: '0.6.9', electron: '33.2.0', agent: 'opo-ivanov', person: 'Иванов Пётр Сергеевич', connected: true,
      server: 'https://hostless.cloud/apps/sysai', home: 'C:\\Users\\ivanov\\SYSAI', profile: 'sysai' }),
    ready: () => {},
    acp: {
      state: async () => (scene === 'boot' ? { state: 'error', message: 'Hermes завершился с кодом 1', stderr: 'ModuleNotFoundError: No module named acp' }
        : { state: 'ready', generation: ++gen, agentInfo: { version: '0.23.1' } }),
      restart: async () => {},
      request: async (method, params) => {
        if (method === 'session/list') return { sessions: scene === 'empty' ? SESSIONS.slice(1) : SESSIONS };
        if (method === 'session/new') return { sessionId: `s-new-${Date.now()}`, configOptions: MODEL };
        if (method === 'session/load') { setTimeout(() => script(params.sessionId), 30); await sleep(80); return { configOptions: MODEL }; }
        if (method === 'session/prompt') { await sleep(1500); return { stopReason: 'end_turn' }; }
        return {};
      },
      notify: async () => {}, respond: async () => {},
      onState: on('acp:state'), onNotification: on('acp:notification'), onRequest: on('acp:request'), onRequestGone: on('acp:request-gone'),
    },
    auto: { get: async () => ({ on: true, count: 3, project: 'Элеватор Благовещенск' }), set: async (v) => ({ on: v, count: 3 }),
      recent: async () => [], undo: async () => ({}), onState: on('auto:state'), onToggle: on('auto:toggle') },
    fs: {
      places: async () => [], drives: async () => [], list: async () => ({ path: 'C:\\', items: [] }),
      info: async (p) => ({ exists: true, path: p, dir: false }), text: async () => '', bytes: async () => new Uint8Array(),
      url: async (p) => `file://${p}`, attachments: async () => ({ items: [], text: '' }), paste: async () => '',
    },
    shell: { open: async () => {}, reveal: async () => {}, run: async () => {}, external: async () => {} },
    dialog: { files: async () => [] }, conv: { export: async () => '' }, clipboard: { write: async () => {} },
    storage: { list: async () => ({ items: [] }), fetch: async () => '', upload: async () => ({}) },
    projects: {
      list: () => rpc('projects:list'), create: (n) => rpc('projects:create', n), info: (n) => rpc('projects:info', n),
      add: async () => ({}), tidy: async () => [], dialog: (n, d) => rpc('projects:dialog', n, d), role: async () => ({}), attach: async () => ({}),
    },
    canvas: { state: async () => ({ open: false }), open: async () => {}, pick: async () => '', window: async () => {}, edit: async () => ({}),
      undo: async () => ({}), reload: async () => {}, close: async () => {}, easybuilder: async () => {}, pointer: () => {},
      onState: on('canvas:state'), onCursors: on('canvas:cursors'), onEdited: on('canvas:edited'), onFocus: on('canvas:focus') },
    win: { overlay: async () => {}, logs: async () => '', onShow: on('ui:show'), onNotice: on('ui:notice') },
    pathForFile: () => '',
  };
  localStorage.setItem('sysai.session.last', scene === 'empty' ? '' : 's-work');
  localStorage.setItem('sysai.project', 'Элеватор Благовещенск');
  localStorage.removeItem('sysai.pane.open');
  if (scene === 'work') addEventListener('load', () => setTimeout(() => document.getElementById('nav-projects').click(), 200));
  if (scene === 'format') {   // «в каком формате сохранить» — варианты с маленькими лого
    setTimeout(() => emit('acp:request', { id: 9001, method: 'elicitation/create', params: {
      sessionId: 's-work',
      message: 'В каком формате сохранить программу ПЛК?',
      requestedSchema: { type: 'object', properties: { answer: { type: 'string',
        enum: ['Machine Expert', 'Haiwell Happy'],
        'x-icons': { 'Machine Expert': 'img/format-me.svg', 'Haiwell Happy': 'img/format-hawell.svg' } } } },
    } }), 900);
  }
  if (scene === 'panel') {    // экраны: сначала формат панели, потом разрешение — панели разные
    setTimeout(() => emit('acp:request', { id: 9002, method: 'elicitation/create', params: {
      sessionId: 's-work',
      message: 'В каком формате рисовать экраны?',
      requestedSchema: { type: 'object', properties: { answer: { type: 'string',
        enum: ['ONI', 'EasyBuilder'],
        'x-icons': { 'ONI': 'img/format-oni.svg', 'EasyBuilder': 'img/format-easybuilder.svg' } } } },
    } }), 600);
    setTimeout(() => emit('acp:request', { id: 9003, method: 'elicitation/create', params: {
      sessionId: 's-work',
      message: 'Под какое разрешение рисовать экраны? Панели разные — экран под 1024×768 на 800×480 не влезает.',
      requestedSchema: { type: 'object', properties: { answer: { type: 'string',
        enum: ['800×480 — 7" панель', '1024×600 — 7" широкая', '1024×768 — 10,4"/12,1"',
               '1280×800 — 10,1"', '1366×768 — 15"', '1920×1080 — 15"/21,5"'] } } },
    } }), 1400);
  }
})();
