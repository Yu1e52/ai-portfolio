"""Persistent local accounts and recruitment scopes; all authorization is server-side."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROLES = {'admin': '平台管理员', 'manager': '招聘经理', 'hr': '招聘专员', 'department': '用人部门'}
DEMO_USERNAMES = ('demo.manager', 'demo.hr.tech', 'demo.hr.product', 'demo.dept.tech', 'demo.dept.product', 'demo.admin')
LOCK = threading.RLock()
SESSIONS = {}
FAILURES = {}
DB_PATH = Path(os.environ.get('RECRUITMENT_DB', str(Path(__file__).with_name('recruitment.sqlite3'))))

class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def now():
    return datetime.now(timezone.utc).isoformat()

def text(value, label, limit=2000, optional=False):
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise Problem(f'{label}不能为空或超过 {limit} 字符。')
    return value.strip()

def uid():
    return secrets.token_hex(12)

def public(row):
    return {k: row[k] for k in ['id', 'username', 'name', 'role', 'department', 'enabled', 'createdAt', 'lastLogin']}

@contextmanager
def db():
    with LOCK:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE, name TEXT, role TEXT, department TEXT, enabled INTEGER, salt TEXT, digest TEXT, createdAt TEXT, lastLogin TEXT)')
            connection.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT)')
            connection.execute('INSERT OR IGNORE INTO state VALUES (1, ?)', (json.dumps({'jobs': [], 'candidates': [], 'referrals': [], 'feedbacks': [], 'audit': []}),))
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

def load(connection):
    return json.loads(connection.execute('SELECT content FROM state WHERE id=1').fetchone()[0])

def save(connection, state):
    connection.execute('UPDATE state SET content=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))

def audit(state, user, action, target):
    state['audit'].append({'id': uid(), 'at': now(), 'by': user['name'], 'byId': user['id'], 'action': action, 'target': target})

def configured():
    with db() as connection:
        return connection.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0

def demo_mode():
    return os.environ.get('RECRUITMENT_DEMO_MODE') == '1'

def demo_users():
    if not demo_mode():
        return []
    with db() as connection:
        rows = connection.execute('SELECT * FROM users WHERE enabled=1').fetchall()
    by_name = {row['username']: public(row) for row in rows if row['username'] in DEMO_USERNAMES}
    return [by_name[name] for name in DEMO_USERNAMES if name in by_name]

def demo_switch(username):
    if not demo_mode():
        raise Problem('演示切换未启用。', 403)
    if username not in DEMO_USERNAMES:
        raise Problem('只能切换到指定的虚构演示账号。', 403)
    with db() as connection:
        row = connection.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE AND enabled=1', (username,)).fetchone()
        if not row:
            raise Problem('演示账号不存在或已停用。', 404)
        user = public(row)
    sid = secrets.token_urlsafe(40)
    SESSIONS[sid] = (user['id'], time.time() + 12 * 3600)
    return sid, user

def password_digest(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()

def new_user(connection, payload, force_admin=False):
    username = text(payload.get('username'), '账号', 60)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,60}', username):
        raise Problem('账号使用 3–60 位英文字母、数字、点、横线或下划线。')
    name = text(payload.get('name'), '姓名', 60)
    password = payload.get('password')
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise Problem('初始密码需为 10–128 个字符。')
    role = 'admin' if force_admin else payload.get('role')
    if role not in ROLES:
        raise Problem('请选择有效角色。')
    department = text(payload.get('department', ''), '部门', 100, optional=role != 'department')
    salt = secrets.token_hex(16)
    identity = uid()
    try:
        connection.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (identity, username, name, role, department, 1, salt, password_digest(password, salt), now(), ''))
    except sqlite3.IntegrityError:
        raise Problem('此账号已存在。') from None
    return public(connection.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone())

def setup(payload):
    with db() as connection:
        if connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            raise Problem('平台已初始化，请登录。', 409)
        user = new_user(connection, payload, True)
        state = load(connection)
        audit(state, user, '初始化管理员', user['id'])
        save(connection, state)
        return user

def login(payload):
    username = text(payload.get('username'), '账号', 60)
    password = payload.get('password', '')
    if not isinstance(password, str) or len(password) > 128:
        raise Problem('账号或密码不正确。', 401)
    with db() as connection:
        stamp = time.time()
        recent = [t for t in FAILURES.get(username.lower(), []) if stamp - t < 60]
        if len(recent) >= 5:
            raise Problem('连续登录失败，请一分钟后重试。', 429)
        row = connection.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone()
        salt = row['salt'] if row else '00' * 16
        valid = hmac.compare_digest(password_digest(password, salt), row['digest'] if row else '0' * 64)
        if not row or not row['enabled'] or not valid:
            FAILURES[username.lower()] = recent + [stamp]
            raise Problem('账号、密码不正确或账号已停用。', 401)
        FAILURES.pop(username.lower(), None)
        connection.execute('UPDATE users SET lastLogin=? WHERE id=?', (now(), row['id']))
        sid = secrets.token_urlsafe(40)
        SESSIONS[sid] = (row['id'], stamp + 12 * 3600)
        return sid, public(connection.execute('SELECT * FROM users WHERE id=?', (row['id'],)).fetchone())

def session(sid):
    with LOCK:
        saved = SESSIONS.get(sid)
        if not saved or saved[1] < time.time():
            SESSIONS.pop(sid, None)
            return None
        with db() as connection:
            row = connection.execute('SELECT * FROM users WHERE id=?', (saved[0],)).fetchone()
            if not row or not row['enabled']:
                SESSIONS.pop(sid, None)
                return None
            return public(row)

def require(user, *roles):
    if not user:
        raise Problem('请先登录。', 401)
    if roles and user['role'] not in roles:
        raise Problem('当前账号没有此操作权限。', 403)

def users(user):
    require(user)
    with db() as connection:
        rows = [public(r) for r in connection.execute('SELECT * FROM users ORDER BY createdAt')]
    if user['role'] == 'admin':
        return rows
    if user['role'] == 'manager':
        return [r for r in rows if r['role'] in ('hr', 'department') and r['enabled']]
    return []

def can_job(user, job):
    return job['managerId'] == user['id'] if user['role'] == 'manager' else job.get('hrId') == user['id'] if user['role'] == 'hr' else False

def scoped(user, state):
    if user['role'] == 'admin':
        return {'jobs': [], 'candidates': [], 'referrals': [], 'feedbacks': [], 'audit': [a for a in state['audit'] if a['action'] in ('初始化管理员', '创建账号', '启用账号', '停用账号')]}
    if user['role'] == 'department':
        refs = [r for r in state['referrals'] if r['department'] == user['department']]
        job_ids, candidate_ids = {r['jobId'] for r in refs}, {r['candidateId'] for r in refs}
        jobs = [j for j in state['jobs'] if j['id'] in job_ids]
        candidates = [c for c in state['candidates'] if c['id'] in candidate_ids]
        # Only referenced versions and referenced review/analysis are released to the department.
        candidates = json.loads(json.dumps(candidates))
        jobs = json.loads(json.dumps(jobs))
        for j in jobs:
            versions = {r['version'] for r in refs if r['jobId'] == j['id']}
            j['versions'] = [v for v in j['versions'] if v['id'] in versions]
        for c in candidates:
            cr = [r for r in refs if r['candidateId'] == c['id']]
            review_ids = {r['reviewId'] for r in cr}
            c['reviews'] = [v for v in c['reviews'] if v['id'] in review_ids]
            analysis_ids = {v.get('analysisId') for v in c['reviews']}
            c['analyses'] = [a for a in c['analyses'] if a['id'] in analysis_ids]
            c['events'] = []
            for field in ('analysisStatus', 'analysisError', 'analysisAttemptAt', 'analysisAttemptBy'):
                c.pop(field, None)
    else:
        jobs = [j for j in state['jobs'] if can_job(user, j)]
        job_ids = {j['id'] for j in jobs}
        candidates = [c for c in state['candidates'] if c['jobId'] in job_ids]
        refs = [r for r in state['referrals'] if r['jobId'] in job_ids]
    ref_ids = {r['id'] for r in refs}
    return {'jobs': jobs, 'candidates': candidates, 'referrals': refs,
            'feedbacks': [f for f in state['feedbacks'] if f['referralId'] in ref_ids], 'audit': []}

def data(user):
    require(user)
    with db() as connection:
        result = scoped(user, load(connection))
    result['users'] = users(user)
    return result

def lookup(items, identity, label):
    found = next((x for x in items if x['id'] == identity), None)
    if not found:
        raise Problem(f'{label}不存在或无权访问。', 404)
    return found

def get_candidate(user, state, identity, role='hr'):
    require(user, role)
    candidate = lookup(state['candidates'], identity, '材料')
    job = lookup(state['jobs'], candidate['jobId'], '岗位')
    if not can_job(user, job):
        raise Problem('岗位未分配给当前账号。', 403)
    return candidate, job

def mutate(user, path, payload):
    require(user)
    with db() as connection:
        state = load(connection)
        if path == '/api/users':
            require(user, 'admin')
            created = new_user(connection, payload)
            audit(state, user, '创建账号', created['id'])
        elif path == '/api/users/status':
            require(user, 'admin')
            row = connection.execute('SELECT * FROM users WHERE id=?', (payload.get('id'),)).fetchone()
            if not row:
                raise Problem('账号不存在。', 404)
            enabled = payload.get('enabled')
            if type(enabled) is not bool:
                raise Problem('账号状态不正确。')
            if row['id'] == user['id'] and not enabled:
                raise Problem('不能在当前会话停用自己的管理员账号。')
            if not enabled and row['role'] == 'admin' and connection.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0] <= 1:
                raise Problem('需保留至少一个启用的管理员账号。')
            connection.execute('UPDATE users SET enabled=? WHERE id=?', (int(enabled), row['id']))
            if not enabled:
                for sid, value in list(SESSIONS.items()):
                    if value[0] == row['id']:
                        SESSIONS.pop(sid, None)
            audit(state, user, '启用账号' if enabled else '停用账号', row['id'])
        elif path == '/api/jobs':
            require(user, 'manager')
            job = lookup(state['jobs'], payload['id'], '岗位') if payload.get('id') else None
            if job and not can_job(user, job):
                raise Problem('不能修改其他经理管理的岗位。', 403)
            name = text(payload.get('name'), '岗位名称', 200)
            department = text(payload.get('department'), '用人部门', 100)
            if not connection.execute("SELECT 1 FROM users WHERE department=? AND role='department' AND enabled=1", (department,)).fetchone():
                raise Problem('请先由管理员创建对应部门账号。')
            req, bonus = payload.get('requirements'), payload.get('bonus', [])
            if not isinstance(req, list) or not req or len(req) > 40 or not isinstance(bonus, list) or len(bonus) > 40:
                raise Problem('每组条件最多 40 项，技能要求不能为空。')
            req = [text(x, '技能条件', 500) for x in req]
            bonus = [text(x, '加分条件', 500) for x in bonus]
            headcount = payload.get('headcount')
            if headcount is not None and (type(headcount) is not int or not 0 <= headcount <= 100000):
                raise Problem('名额需为非负整数，未提供请留空。')
            v = {'id': uid(), 'label': 'v' + str(len(job['versions']) + 1 if job else 1), 'requirements': req, 'bonus': bonus, 'source': text(payload.get('source'), '要求来源'), 'at': now(), 'by': user['name']}
            if job:
                if department != job['department']:
                    raise Problem('已有岗位不直接更换部门，请为新的目标部门另建岗位，保留历史推荐。')
                job.update({'name': name, 'headcount': headcount})
                job['versions'].append(v)
            else:
                job = {'id': uid(), 'name': name, 'department': department, 'managerId': user['id'], 'managerName': user['name'], 'hrId': None, 'hrName': '', 'headcount': headcount, 'versions': [v]}
                state['jobs'].append(job)
            audit(state, user, '维护岗位要求', job['id'])
        elif path == '/api/assign':
            require(user, 'manager')
            job = lookup(state['jobs'], payload.get('jobId'), '岗位')
            if not can_job(user, job):
                raise Problem('不能分配其他经理管理的岗位。', 403)
            hr = connection.execute("SELECT * FROM users WHERE id=? AND role='hr' AND enabled=1", (payload.get('hrId'),)).fetchone()
            if not hr:
                raise Problem('请选择启用的招聘专员账号。')
            previous = job.get('hrName') or '未分配'
            job.update({'hrId': hr['id'], 'hrName': hr['name']})
            audit(state, user, '分配招聘专员', job['id'])
            job.setdefault('assignments', []).append({'at': now(), 'by': user['name'], 'from': previous, 'to': hr['name']})
        elif path == '/api/candidates':
            require(user, 'hr')
            job = lookup(state['jobs'], payload.get('jobId'), '岗位')
            if not can_job(user, job):
                raise Problem('只能为分配给自己的岗位导入材料。', 403)
            resume = text(payload.get('text'), '简历正文', 60000)
            batch = payload.get('batchId')
            if batch is not None and (not isinstance(batch, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', batch)):
                raise Problem('导入批次标识不正确。')
            duplicate = any(c['jobId'] == job['id'] and c['text'] == resume for c in state['candidates'])
            c = {'id': uid(), 'name': text(payload.get('name'), '材料名称', 250), 'fileName': text(payload.get('fileName', '粘贴正文'), '文件名', 250), 'source': text(payload.get('source', '未注明'), '来源', 100), 'text': resume, 'jobId': job['id'], 'createdBy': user['id'], 'at': now(), 'analyses': [], 'reviews': [], 'events': [], 'duplicate': duplicate, 'batchId': batch or '', 'analysisStatus': 'unscored', 'analysisError': '', 'analysisAttemptAt': '', 'analysisAttemptBy': ''}
            c['events'].append({'at': now(), 'by': user['name'], 'text': '登记材料并关联岗位；未生成评分或淘汰结论。' + ('批量导入批次 ' + batch + '。' if batch else '')})
            state['candidates'].append(c)
        elif path == '/api/reviews':
            c, job = get_candidate(user, state, payload.get('candidateId'))
            v = job['versions'][-1]
            if payload.get('version') != v['id']:
                raise Problem('岗位要求已变化，请刷新并重新核实。', 409)
            decision, opinion = payload.get('decision'), payload.get('match')
            if decision not in ('pass', 'fail', 'more') or opinion not in ('yes', 'partial', 'no', 'unknown'):
                raise Problem('请明确选择审核结论和独立匹配判断。')
            analyses = [a for a in c['analyses'] if a['version'] == v['id']]
            c['reviews'].append({'id': uid(), 'version': v['id'], 'decision': decision, 'match': opinion, 'reason': text(payload.get('reason'), '判断依据'), 'analysisId': analyses[-1]['id'] if analyses else None, 'at': now(), 'by': user['name'], 'byId': user['id']})
            c['events'].append({'at': now(), 'by': user['name'], 'text': '保存独立人工审核；未改写 AI 原意见。'})
        elif path == '/api/referrals':
            c, job = get_candidate(user, state, payload.get('candidateId'))
            current = job['versions'][-1]
            reviews = [r for r in c['reviews'] if r['version'] == current['id']]
            if not reviews or reviews[-1]['decision'] != 'pass':
                raise Problem('需按当前岗位版本人工审核通过，才能推荐。')
            review = reviews[-1]
            if payload.get('department') != job['department']:
                raise Problem('推荐部门需与目标岗位一致；其他部门请使用其对应岗位独立审核。')
            if any(r['reviewId'] == review['id'] for r in state['referrals']):
                raise Problem('本次审核已推荐，无需重复提交。', 409)
            state['referrals'].append({'id': uid(), 'candidateId': c['id'], 'jobId': job['id'], 'version': review['version'], 'reviewId': review['id'], 'department': job['department'], 'at': now(), 'by': user['name']})
            c['events'].append({'at': now(), 'by': user['name'], 'text': '明确推荐至 ' + job['department'] + '；保留当时岗位及审核版本。'})
        elif path == '/api/feedback':
            require(user, 'department')
            ref = lookup(state['referrals'], payload.get('referralId'), '推荐记录')
            if ref['department'] != user['department']:
                raise Problem('只能反馈推荐给本部门的材料。', 403)
            stage, opinion = payload.get('stage'), payload.get('match')
            if stage not in ('简历评估', '面试后', '试岗后') or opinion not in ('yes', 'partial', 'no', 'unknown'):
                raise Problem('请明确反馈阶段与专业匹配意见。')
            outcome = payload.get('outcome', '')
            if outcome not in ('', '面试通过', '试岗中', '未录用', '已入职'):
                raise Problem('招聘结果不正确。')
            confirmed = payload.get('confirmed', False)
            if type(confirmed) is not bool:
                raise Problem('确认状态不正确。')
            occurred = payload.get('occurred', '')
            if occurred:
                try:
                    datetime.strptime(occurred, '%Y-%m-%d')
                except (ValueError, TypeError):
                    raise Problem('事实日期不正确。') from None
            if outcome == '已入职' and confirmed and not occurred:
                raise Problem('确认入职时需填写事实日期。')
            state['feedbacks'].append({'id': uid(), 'referralId': ref['id'], 'stage': stage, 'match': opinion, 'reason': text(payload.get('reason'), '专业依据'), 'outcome': outcome, 'confirmed': confirmed, 'occurred': occurred, 'by': user['name'], 'byId': user['id'], 'at': now()})
        else:
            raise Problem('操作不存在。', 404)
        save(connection, state)
    return {'ok': True}

def analysis_context(user, candidate_id):
    with db() as connection:
        state = load(connection)
        c, job = get_candidate(user, state, candidate_id)
        v = job['versions'][-1]
        return {'candidateId': c['id'], 'jobId': job['id'], 'version': v['id'], 'resume': c['text'],
                'job': {'name': job['name'], 'requirements': v['requirements'], 'bonus': v['bonus']}}

def save_analysis(user, context, result):
    # Recheck assignment and enabled status after the remote request completes.
    with db() as connection:
        row = connection.execute('SELECT * FROM users WHERE id=? AND enabled=1', (user['id'],)).fetchone()
        if not row:
            raise Problem('模型已返回，但当前账号已停用，未写入。', 403)
        current_user = public(row)
        state = load(connection)
        c, job = get_candidate(current_user, state, context['candidateId'])
        if job['id'] != context.get('jobId') or job['versions'][-1]['id'] != context['version'] or c['text'] != context['resume']:
            raise Problem('模型已返回，但原岗位版本或材料已变化，未写入。', 409)
        record = dict(result, id=uid(), by=user['name'], byId=user['id'])
        c['analyses'].append(record)
        c.update({'analysisStatus': 'scored', 'analysisError': '', 'analysisAttemptAt': now(),
                  'analysisAttemptBy': user['name']})
        c['events'].append({'at': now(), 'by': user['name'], 'text': '新增 DeepSeek 评分历史；不修改人工审核或部门反馈。'})
        save(connection, state)
    return record


def record_analysis_failure(user, context, message):
    with db() as connection:
        row = connection.execute('SELECT * FROM users WHERE id=? AND enabled=1', (user['id'],)).fetchone()
        if not row:
            raise Problem('当前账号已停用，评分失败状态未写入。', 403)
        current_user = public(row)
        state = load(connection)
        c, job = get_candidate(current_user, state, context['candidateId'])
        if job['id'] != context.get('jobId') or job['versions'][-1]['id'] != context['version'] or c['text'] != context['resume']:
            raise Problem('岗位版本或材料已变化，评分失败状态未写入。', 409)
        c.update({'analysisStatus': 'failed', 'analysisError': str(message)[:500],
                  'analysisAttemptAt': now(), 'analysisAttemptBy': user['name']})
        c['events'].append({'at': now(), 'by': user['name'], 'text': 'DeepSeek 评分失败；未保存分数，人工审核和旧评分不变。'})
        save(connection, state)
