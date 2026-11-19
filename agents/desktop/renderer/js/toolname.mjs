// How a row of an action is named: the title Hermes gives a tool call («<tool>: <preview>», acp_adapter/tools.py
// build_tool_title) → a Russian label, the detail and an icon. MCP tools of Hermes are «mcp__<server>__<tool>» (the
// server name with «-» as «_»); older Hermes said «mcp_<server>_<tool>». With Tool Search on, a hub tool is reached
// through «tool_call» / «tool_describe» and the real tool is in the preview. No DOM here: the unit tests import it.

export const TOOL_RU = {
  terminal: 'Команда', execute_code: 'Код', read_file: 'Читает', write_file: 'Записывает', patch: 'Правит',
  search_files: 'Ищет', web_search: 'Ищет в интернете', web_extract: 'Читает страницу', vision_analyze: 'Смотрит картинку',
  delegate_task: 'Поручает помощникам', memory: 'Память', todo: 'План', todo_list: 'План', skill_view: 'Навык',
  skills_list: 'Навыки', skill_manage: 'Навык', session_search: 'Прошлые разговоры', clarify: 'Вопрос',
  process: 'Процесс', process_manage: 'Процесс', computer_use: 'Управляет ПК', cronjob: 'Расписание',
  text_to_speech: 'Озвучивает', image_generate: 'Рисует', send_message: 'Сообщение', mixture_of_agents: 'Совет моделей',
  tool_search: 'Ищет инструмент', tool_describe: 'Смотрит инструмент', browser_exec: 'Браузер',
};
export const NAME_ICON = { terminal: 'terminal', execute_code: 'code', read_file: 'eye', write_file: 'pencil', patch: 'pencil',
  search_files: 'search', web_search: 'globe', web_extract: 'globe', vision_analyze: 'image', delegate_task: 'users',
  memory: 'memory', todo: 'list', todo_list: 'list', skill_view: 'book', skills_list: 'book', skill_manage: 'book',
  session_search: 'clock', clarify: 'help', computer_use: 'monitor', cronjob: 'clock', tool_search: 'search',
  tool_describe: 'book' };
export const KIND_ICON = { read: 'eye', edit: 'pencil', delete: 'trash', move: 'folder', search: 'search', execute: 'terminal',
  think: 'spark', fetch: 'globe', switch_mode: 'sliders', other: 'spark' };

// the servers SYSAI gives: what the person reads instead of «plc_kit»
export const SERVER_RU = {
  window: ['Окно', 'monitor'], sysai: ['SYSAI', 'cloud'], 'plc-kit': ['ПЛК', 'cube'], 'plc-live': ['Контроллер', 'cube'],
  'machine-expert': ['Machine Expert', 'cube'], 'ebpro-cmtp': ['EasyBuilder', 'canvas'], 'ebpro-gui': ['EasyBuilder', 'monitor'],
  'doc-kit': ['Документы', 'fileText'], 'drawing-kit': ['Чертежи', 'image'], 'pic-index': ['Картинки', 'image'],
};
const SERVER_BY_KEY = Object.fromEntries(Object.keys(SERVER_RU).map((k) => [k.replace(/-/g, '_'), k]));

export const WINDOW_TOOL = { show_file: 'Показывает файл', open_file: 'Открывает в программе', show_in_folder: 'Показывает в папке',
  canvas_open: 'Открывает на холсте', canvas_look: 'Смотрит на холст', canvas_window: 'Окно на холсте',
  canvas_cursor: 'Курсор на холсте', canvas_edit: 'Правит на холсте' };

// what a few tools do, in words: the rest show their own name
const TOOL_WORDS = {
  plc_stage_update: 'этап', plc_generate: 'пишет программу', plc_project_build: 'собирает проект', plc_build: 'собирает',
  plc_check: 'проверяет программу', plc_spec_check: 'проверяет спецификацию', plc_spec_new: 'новая спецификация',
  plc_io_map: 'распределяет каналы', plc_hmi_tags: 'теги панели', me_build: 'компилирует', me_create: 'создаёт проект',
  me_update: 'обновляет проект', me_online: 'контроллер', me_scan: 'ищет контроллеры', me_open: 'открывает проект',
  me_export: 'достаёт программу', plc_read: 'читает переменные', plc_watch: 'наблюдает', plc_scan: 'ищет в сети',
  cmtp_render: 'рисует окно', cmtp_edit: 'правит проект', cmtp_check: 'проверяет экраны', cmtp_scene: 'читает окно',
  cmtp_windows: 'окна', cmtp_objects: 'объекты', cmtp_tags: 'теги', cmtp_info: 'проект', cmtp_links: 'переходы',
};
const STAGE_RU = { materials: 'материалы', decisions: 'решения', plc: 'программа ПЛК', build: 'сборка', hmi: 'экраны', docs: 'документы' };
const STATE_RU = { work: 'в работе', done: 'готово', problem: 'вопрос', todo: 'не начат' };

// «mcp__plc_kit__plc_stage_update» / «mcp_window_show_file» → { server: 'plc-kit', tool: 'plc_stage_update' }
export function splitMcp(name) {
  const s = String(name || '');
  let m = /^mcp__(.+?)__(.+)$/.exec(s);
  if (m) return { server: SERVER_BY_KEY[m[1]] || m[1].replace(/_/g, '-'), tool: m[2] };
  m = /^mcp_(.+)$/.exec(s);
  if (!m) return null;
  const rest = m[1];
  const known = Object.keys(SERVER_BY_KEY).sort((a, b) => b.length - a.length).find((k) => rest.startsWith(`${k}_`));
  if (known) return { server: SERVER_BY_KEY[known], tool: rest.slice(known.length + 1) };
  const [server, ...tool] = rest.split('_');
  return { server, tool: tool.join('_') };
}

// «D:\\ОПО\\Элеватор\\plc\\Elevator.project» → «…\\plc\\Elevator.project»: the row is one line, the full path is in the details
export function shortPaths(text) {
  const short = (p) => {
    const sep = p.includes('\\') ? '\\' : '/';
    const parts = p.split(/[\\/]/).filter(Boolean);
    return parts.length > 3 ? `…${sep}${parts.slice(-2).join(sep)}` : p;
  };
  // a part that is a whole absolute path (names with spaces too), otherwise the paths inside the text
  return text.split(' · ').map((part) => (/^([A-Za-z]:[\\/]|\/|\\\\)[^:*?"<>|]*$/.test(part.trim()) ? short(part.trim())
    : part.replace(/(?:[A-Za-z]:[\\/]|\/)(?:[^\s\\/·]+[\\/]){3,}[^\s\\/·]*/g, short))).join(' · ');
}

function stageDetail(input) {
  if (!input || typeof input !== 'object' || !input.stage) return '';
  const stage = STAGE_RU[input.stage] || input.stage;
  const state = STATE_RU[input.state] || input.state || '';
  return `«${stage}»${state ? ` → ${state}` : ''}` + (input.note ? ` · ${String(input.note)}` : '');
}

export function describeTool(data) {
  const title = String(data.title || '').trim();
  const m = /^([A-Za-z_][\w.-]*):\s*([\s\S]*)$/.exec(title);
  let name = m ? m[1] : (/^[A-Za-z_][\w.-]*$/.test(title) ? title : '');
  let detail = m ? m[2] : (name ? '' : title);
  let input = data.rawInput && typeof data.rawInput === 'object' ? data.rawInput : null;
  // through Tool Search: «tool_call: mcp__plc_kit__plc_stage_update …» — the row is about the real tool
  if (name === 'tool_call') {
    const inner = (input && (input.name || input.tool_name || input.tool)) || (/^(mcp_\S+)/.exec(detail) || [])[1] || '';
    if (inner) {
      name = String(inner);
      detail = detail.replace(/^\S+\s*/, '');
      if (input && input.arguments && typeof input.arguments === 'object') input = input.arguments;
    }
  }
  let label = TOOL_RU[name] || '';
  let ico = NAME_ICON[name] || KIND_ICON[data.kind] || 'spark';
  if (!label && name.startsWith('browser_')) { label = 'Браузер'; ico = 'globe'; detail = detail || name.slice(8); }
  const mcp = !label && splitMcp(name);
  if (mcp) {
    const [server, serverIcon] = SERVER_RU[mcp.server] || [mcp.server, 'cube'];
    ico = serverIcon;
    if (mcp.server === 'window') {
      label = WINDOW_TOOL[mcp.tool] || 'Окно';
    } else {
      label = server;
      const words = mcp.tool === 'plc_stage_update' ? (stageDetail(input) ? `этап ${stageDetail(input)}` : 'этапы проекта')
        : TOOL_WORDS[mcp.tool] || mcp.tool;
      detail = [words, mcp.tool === 'plc_stage_update' && stageDetail(input) ? '' : detail].filter(Boolean).join(' · ');
    }
  }
  if (!label) label = name || (data.kind === 'think' ? 'Думает' : 'Действие');
  detail = shortPaths(String(detail));
  if (!detail && data.locations && data.locations.length) detail = data.locations.map((l) => l.path).join(', ');
  return { name, label, detail: String(detail).replace(/\s+/g, ' ').trim(), icon: ico, server: mcp ? mcp.server : '',
    tool: mcp ? mcp.tool : '' };
}

function textOf(content) {
  if (!content) return '';
  if (typeof content === 'string') return content;
  if (content.type === 'text') return content.text || '';
  if (content.type === 'resource' && content.resource) return content.resource.text || '';
  return '';
}

// a hub server answers a failed call as a result «ОШИБКА (plc-kit/…): …» (the wrapper of the synchronizer): the
// server is alive and the agent fixes the call — a warning in the row, not a check mark
export function answeredError(d) {
  const texts = [];
  for (const c of (d && d.content) || []) if (c && c.type === 'content') texts.push(textOf(c.content) || '');
  if (d && typeof d.rawOutput === 'string') texts.push(d.rawOutput);
  else if (d && d.rawOutput && typeof d.rawOutput === 'object') texts.push(String(d.rawOutput.result || ''));
  return texts.some((x) => /^[\s{"]*(result"\s*:\s*")?ОШИБКА \(/.test(String(x).slice(0, 200)));
}
