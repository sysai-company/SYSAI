"""Именованные стили проекта ПЛК: то, что инженер переносит в следующий проект.

Стиль — это профиль `plcme.Project.style()` готового проекта, сохранённый под именем (Vendor, Достоево) и
использованный снова: `plc_generate(style=...)` пишет следующую программу в той же манере — тот же регистр имён,
тот же суффикс классов, те же группы глобального списка, та же плотность и язык комментариев.

Профиль не описывает, что делает программа (это спецификация), — только как она написана.
"""
import json
import os
import re

MARK = 'sysai-style'
DEFAULT_DIR = os.path.join(os.path.expanduser('~'), '.sysai', 'styles')
MAX_BYTES = 1_000_000


class StyleError(Exception):
    pass


def folder(path: str = '') -> str:
    """Где лежат стили: папка из аргумента, из SYSAI_STYLES или ~/.sysai/styles."""
    return path or os.environ.get('SYSAI_STYLES') or DEFAULT_DIR


def _slug(name: str) -> str:
    s = re.sub(r'[^\w.-]+', '-', str(name or '').strip(), flags=re.UNICODE).strip('-')
    if not s:
        raise StyleError('у стиля должно быть имя: назовите его так, как будете выбирать (Vendor, Достоево)')
    return s[:80]


def _file(name: str, path: str = '') -> str:
    return os.path.join(folder(path), _slug(name) + '.json')


def save(profile: dict, name: str, note: str = '', path: str = '') -> dict:
    """Записать профиль проекта как именованный стиль. -> {name, file, style}"""
    if not isinstance(profile, dict) or not profile.get('project'):
        raise StyleError('профиль пуст: сначала plc_style на готовом проекте, потом сохранять')
    data = {'mark': MARK, 'name': str(name), 'note': str(note or ''), 'style': profile}
    f = _file(name, path)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    return {'name': data['name'], 'file': f, 'style': profile}


def listing(path: str = '') -> list:
    """Сохранённые стили: имя, заметка, откуда снят, и те немногие числа, что отличают один стиль от другого."""
    out = []
    d = folder(path)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith('.json'):
            continue
        f = os.path.join(d, fn)
        try:
            if os.path.getsize(f) > MAX_BYTES:
                continue
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get('mark') != MARK:
            continue
        st = data.get('style') if isinstance(data.get('style'), dict) else {}
        naming = st.get('naming') if isinstance(st.get('naming'), dict) else {}
        out.append({'name': data.get('name') or fn[:-5], 'note': data.get('note') or '',
                    'from': st.get('project') or '', 'controller': st.get('controller') or '',
                    'programs': len(st.get('programs') or []), 'classes': len(st.get('classes') or []),
                    'case': naming.get('case') or '', 'class_suffix': naming.get('class_suffix') or '',
                    'file': f})
    return out


def load(name: str, path: str = '') -> dict:
    f = _file(name, path)
    try:
        if os.path.getsize(f) > MAX_BYTES:
            raise StyleError(f'файл стиля «{name}» больше 1 МБ: это не он')
        with open(f, encoding='utf-8') as fh:
            data = json.load(fh)
    except OSError:
        raise StyleError(f'стиля «{name}» нет: сохраните его plc_style_save на готовом проекте') from None
    except ValueError:
        raise StyleError(f'файл стиля «{name}» испорчен: {f}') from None
    if not isinstance(data, dict) or data.get('mark') != MARK:
        raise StyleError(f'{f} — не файл стиля SYSAI')
    st = data.get('style')
    if not isinstance(st, dict):
        raise StyleError(f'в файле стиля «{name}» нет профиля')
    return st


def _case_name(name: str, case: str) -> str:
    """То же имя в регистре стиля: snake_case разделяет слова, CamelCase склеивает."""
    if not case or not name:
        return name
    words = [w for w in re.split(r'[_\s]+', name) if w]
    if not words:
        return name
    if case == 'snake_case':
        return '_'.join(w.lower() for w in words)
    if case == 'CamelCase':
        head = words[0][:1].lower() + words[0][1:]
        return head + ''.join(w[:1].upper() + w[1:] for w in words[1:])
    return name


def apply_to_spec(spec: dict, style: dict) -> tuple:
    """Спецификация, переписанная в манере стиля. -> (spec, changes) — changes: что и на что заменено.

    Меняются только имена (регистр, суффикс класса), не смысл: механизмы, их блокировки, маршруты и глобальные
    сигналы переименовываются вместе, чтобы ссылки не разъехались. Спецификация не портится — возвращается копия.
    """
    if not isinstance(spec, dict) or not isinstance(style, dict):
        return spec, []
    naming = style.get('naming') if isinstance(style.get('naming'), dict) else {}
    case = str(naming.get('case') or '')
    suffix = str(naming.get('class_suffix') or '')
    if not case and not suffix:
        return spec, []
    out = json.loads(json.dumps(spec))
    changes = []

    mechs = [m for m in (out.get('mechanisms') or []) if isinstance(m, dict)]
    rename = {}
    for m in mechs:
        old = str(m.get('id') or '')
        new = _case_name(old, case)
        if new and new != old:
            rename[old] = new
            m['id'] = new
            changes.append(f'механизм {old} → {new}')
    for m in mechs:  # блокировки ссылаются на другие механизмы — их имена едут вместе
        locks = m.get('interlocks')
        if isinstance(locks, dict):
            for rule, other in list(locks.items()):
                if str(other) in rename:
                    locks[rule] = rename[str(other)]
    for r in out.get('routes') or []:
        if isinstance(r, dict):
            for key in ('mechanisms', 'chain'):   # в спецификации — mechanisms, во внутренней модели — chain
                if isinstance(r.get(key), list):
                    r[key] = [rename.get(str(x), x) for x in r[key]]

    for s in out.get('signals') or []:
        if isinstance(s, dict):
            old = str(s.get('id') or '')
            new = _case_name(old, case)
            if new and new != old:
                s['id'] = new
                changes.append(f'сигнал {old} → {new}')

    if suffix:
        for kind, t in (out.get('types') or {}).items():
            if not isinstance(t, dict):
                continue
            fb = str(t.get('fb') or '')
            if fb and not fb.endswith(suffix):
                t['fb'] = fb + suffix
                changes.append(f'класс {kind}: {fb} → {fb + suffix}')
    return out, changes


def compare(profile: dict, style: dict) -> list:
    """Чем проект расходится со стилем: [{level, where, text}] — для plc_check. Пусто — написан в манере стиля."""
    issues = []
    if not isinstance(profile, dict) or not isinstance(style, dict):
        return issues
    a = profile.get('naming') if isinstance(profile.get('naming'), dict) else {}
    b = style.get('naming') if isinstance(style.get('naming'), dict) else {}
    if a.get('case') and b.get('case') and a['case'] != b['case']:
        issues.append({'level': 'warning', 'where': 'имена',
                       'text': f"регистр имён {a['case']}, а в стиле «{style.get('project') or ''}» — {b['case']}"})
    if a.get('class_suffix') != b.get('class_suffix'):
        issues.append({'level': 'info', 'where': 'классы',
                       'text': f"суффикс классов «{a.get('class_suffix') or 'нет'}», в стиле — "
                               f"«{b.get('class_suffix') or 'нет'}»"})
    ca = (a.get('comments') or {}).get('share')
    cb = (b.get('comments') or {}).get('share')
    if isinstance(ca, (int, float)) and isinstance(cb, (int, float)) and abs(ca - cb) > 0.3:
        issues.append({'level': 'info', 'where': 'комментарии',
                       'text': f'прокомментировано {ca:.0%} переменных, в стиле — {cb:.0%}'})
    ga = [g.get('name') for g in (profile.get('groups') or []) if isinstance(g, dict)]
    gb = [g.get('name') for g in (style.get('groups') or []) if isinstance(g, dict)]
    if ga and gb and ga != gb:
        issues.append({'level': 'info', 'where': 'группы',
                       'text': f'группы {", ".join(map(str, ga))}; в стиле — {", ".join(map(str, gb))}'})
    return issues
