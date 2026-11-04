"""为本地练习平台一次性建立虚构账号、岗位和简历；不会覆盖已有数据。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / 'recruitment.sqlite3'
TEMP_DATABASE = ROOT / '.recruitment_seed_tmp.sqlite3'
CREDENTIALS = ROOT / '演示账号登录信息.md'
TEMP_CREDENTIALS = ROOT / '.演示账号登录信息.tmp'

if DATABASE.exists() or CREDENTIALS.exists():
    raise SystemExit('正式演示数据库或账号文件已存在；为保护现有数据，本脚本不会重复运行。')
if TEMP_DATABASE.exists() or TEMP_CREDENTIALS.exists():
    raise SystemExit('发现上次未完成的临时文件，请先检查后再运行。')

os.environ['RECRUITMENT_DB'] = str(TEMP_DATABASE)
import recruitment_store as store  # noqa: E402


ACCOUNTS = [
    ('demo.manager', '演示招聘经理', 'manager', '人力资源部'),
    ('demo.hr.tech', '演示招聘专员·技术', 'hr', '人力资源部'),
    ('demo.hr.product', '演示招聘专员·产品', 'hr', '人力资源部'),
    ('demo.dept.tech', '演示技术部面试官', 'department', '技术部'),
    ('demo.dept.product', '演示产品部面试官', 'department', '产品部'),
]

# 纯虚构、无联系方式或真实身份信息；岗位数量和名额只服务于界面演示。
TECH_CVS = [
    ('演示简历 T01｜前端组件与性能', '邮件', '从事前端页面开发练习，使用 JavaScript、React 与 TypeScript 完成组件库；描述了列表虚拟滚动、代码拆分和性能分析；有设计系统协作记录。'),
    ('演示简历 T02｜Vue 页面开发', '招聘软件', '主要使用 Vue 和 JavaScript 构建后台页面，熟悉表单与图表；材料未提供 React 项目或性能排查案例，愿意补充。'),
    ('演示简历 T03｜服务端方向', '校园招聘', '以 Python 服务端练习和数据库课程项目为主；简历没有前端框架、页面性能或组件设计相关证据。'),
    ('演示简历 T04｜React 基础项目', '邮件', '完成 React 与 JavaScript 课程项目，包括登录页面、状态管理和接口联调；尚未写明性能优化方法，需由 HR 进一步核实。'),
    ('演示简历 T05｜信息待补', '招聘软件', '仅写有“参与网页项目，了解 JavaScript”，没有具体职责、项目结果或 React 使用细节；应归为材料信息不足，不能自动视为不匹配。'),
    ('演示简历 T06｜组件库实践', '校园招聘', '虚构实习练习中搭建 React、TypeScript 组件示例，编写文档与可访问性用例；提及性能测试，但缺少量化结果。'),
]
PRODUCT_CVS = [
    ('演示简历 P01｜需求与原型', '邮件', '完成用户访谈、需求拆解、原型和验收文档练习；能说明跨团队对齐与版本复盘过程，另有数据分析课程项目。'),
    ('演示简历 P02｜协作交付', '招聘软件', '参与多方协作项目，整理需求文档、流程图和评审结论；有产品原型练习，但尚缺企业服务场景经验。'),
    ('演示简历 P03｜内容运营', '校园招聘', '主要是内容编辑与活动执行练习；材料未体现产品需求分析、原型设计或产品交付。'),
    ('演示简历 P04｜企业服务与数据', '邮件', '围绕企业服务场景做需求调研、原型制作和指标看板练习；对业务部门进行过跨团队沟通模拟。'),
    ('演示简历 P05｜材料不足', '招聘软件', '仅写“希望从事产品工作”，未给出项目、职责或作品；需补充资料后才能形成匹配意见。'),
    ('演示简历 P06｜用户故事', '校园招聘', '能编写用户故事、简单 PRD 与原型，使用基础数据指标复盘；跨部门推进经验尚未写明。'),
]


def snapshot():
    with store.db() as connection:
        return store.load(connection)


def identity(username):
    return next(x for x in store.users(admin) if x['username'] == username)


def job_named(name):
    return next(x for x in snapshot()['jobs'] if x['name'] == name)


def candidate_named(name):
    return next(x for x in snapshot()['candidates'] if x['name'] == name)


passwords = {'demo.admin': secrets.token_urlsafe(18)}
for username, *_ in ACCOUNTS:
    passwords[username] = secrets.token_urlsafe(18)

try:
    admin = store.setup({'username': 'demo.admin', 'name': '演示平台管理员', 'password': passwords['demo.admin'], 'department': '信息技术部'})
    for username, name, role, department in ACCOUNTS:
        store.mutate(admin, '/api/users', {'username': username, 'name': name, 'role': role, 'department': department, 'password': passwords[username]})

    manager = identity('demo.manager')
    tech_hr = identity('demo.hr.tech')
    product_hr = identity('demo.hr.product')
    tech_dept = identity('demo.dept.tech')
    product_dept = identity('demo.dept.product')

    jobs = [
        ('前端开发工程师（虚构演示）', '技术部', ['JavaScript 页面开发', 'React 组件开发', '前端性能分析'], ['TypeScript', '设计系统协作'], 2, tech_hr),
        ('产品经理（虚构演示）', '产品部', ['需求分析与文档', '原型设计', '跨部门协作'], ['企业服务场景经验', '数据分析'], None, product_hr),
    ]
    for name, department, requirements, bonus, headcount, hr in jobs:
        store.mutate(manager, '/api/jobs', {
            'name': name, 'department': department, 'requirements': requirements,
            'bonus': bonus, 'headcount': headcount,
            'source': '虚构演示岗位要求；仅用于练习和客户沟通，不代表真实招聘需求。',
        })
        store.mutate(manager, '/api/assign', {'jobId': job_named(name)['id'], 'hrId': hr['id']})

    tech_job = job_named('前端开发工程师（虚构演示）')
    product_job = job_named('产品经理（虚构演示）')
    for prefix, records, job, hr in [('T', TECH_CVS, tech_job, tech_hr), ('P', PRODUCT_CVS, product_job, product_hr)]:
        for i, (name, source, body) in enumerate(records, 1):
            store.mutate(hr, '/api/candidates', {
                'jobId': job['id'], 'name': name, 'fileName': f'虚构演示_{prefix}{i:02d}.txt',
                'source': source, 'text': '【纯虚构演示简历｜不对应任何真实候选人】\n' + body,
            })

    # 保留未审核、待补充、未反馈等状态，以便在现场展示完整工作流。
    reviews = [
        (tech_hr, tech_job, '演示简历 T01｜前端组件与性能', 'pass', 'yes', '演示人工审核：材料覆盖主要技能，可推荐部门继续核实。', True),
        (tech_hr, tech_job, '演示简历 T02｜Vue 页面开发', 'pass', 'partial', '演示人工改判：虽然 React 证据不足，仍决定推荐部门核实迁移能力。', True),
        (tech_hr, tech_job, '演示简历 T03｜服务端方向', 'fail', 'no', '演示人工审核：目前材料缺少岗位关键技能证据，材料仍被保留。', False),
        (tech_hr, tech_job, '演示简历 T05｜信息待补', 'more', 'unknown', '演示人工审核：资料不足，待候选人补充，不能直接判为低匹配。', False),
        (product_hr, product_job, '演示简历 P01｜需求与原型', 'pass', 'yes', '演示人工审核：需求、原型及协作材料较完整。', True),
        (product_hr, product_job, '演示简历 P02｜协作交付', 'pass', 'partial', '演示人工审核：可推荐专业部门核实企业服务适配度。', True),
        (product_hr, product_job, '演示简历 P05｜材料不足', 'more', 'unknown', '演示人工审核：缺少可判断的项目依据，需要补充材料。', False),
    ]
    for hr, job, name, decision, match, reason, refer in reviews:
        candidate = candidate_named(name)
        store.mutate(hr, '/api/reviews', {
            'candidateId': candidate['id'], 'version': job['versions'][-1]['id'],
            'decision': decision, 'match': match, 'reason': reason,
        })
        if refer:
            store.mutate(hr, '/api/referrals', {'candidateId': candidate['id'], 'department': job['department']})

    state = snapshot()
    def referral_for(name):
        candidate = candidate_named(name)
        return next(x for x in state['referrals'] if x['candidateId'] == candidate['id'])

    store.mutate(tech_dept, '/api/feedback', {
        'referralId': referral_for('演示简历 T01｜前端组件与性能')['id'],
        'stage': '试岗后', 'match': 'yes', 'reason': '演示部门反馈：岗位技能得到验证。',
        'outcome': '已入职', 'confirmed': True, 'occurred': '2026-10-24',
    })
    store.mutate(tech_dept, '/api/feedback', {
        'referralId': referral_for('演示简历 T02｜Vue 页面开发')['id'],
        'stage': '简历评估', 'match': 'no', 'reason': '演示意见冲突：部门认为现有 React 经验证据仍不足；待 HR 跟进，不等同于录用结论。',
        'outcome': '', 'confirmed': False,
    })
    store.mutate(product_dept, '/api/feedback', {
        'referralId': referral_for('演示简历 P01｜需求与原型')['id'],
        'stage': '简历评估', 'match': 'partial', 'reason': '演示部门反馈：基础能力可见，需面试核实场景经验。',
        'outcome': '', 'confirmed': False,
    })

    content = [
        '# 虚构演示账号登录信息', '',
        '> 仅用于本地练习和客户原型沟通。以下账号、岗位、简历、审核和部门反馈均为虚构数据，不代表真实招聘业务。此文件含明文演示密码，请不要用于生产环境或作为真实候选人资料发送。', '',
        '访问地址：<http://127.0.0.1:8772/>', '',
        '| 角色 | 登录账号 | 演示密码 | 可体验的内容 |',
        '| --- | --- | --- | --- |',
        f'| 平台管理员 | `demo.admin` | `{passwords["demo.admin"]}` | 管理账号与角色 |',
        f'| 招聘经理 | `demo.manager` | `{passwords["demo.manager"]}` | 岗位、专员分配和招聘进度 |',
        f'| 招聘专员（技术） | `demo.hr.tech` | `{passwords["demo.hr.tech"]}` | 技术岗位、简历、审核与推荐 |',
        f'| 招聘专员（产品） | `demo.hr.product` | `{passwords["demo.hr.product"]}` | 产品岗位、简历、审核与推荐 |',
        f'| 用人部门（技术） | `demo.dept.tech` | `{passwords["demo.dept.tech"]}` | 技术部收到的推荐与反馈 |',
        f'| 用人部门（产品） | `demo.dept.product` | `{passwords["demo.dept.product"]}` | 产品部收到的推荐与反馈 |',
        '',
        '演示数据：2 个虚构岗位、12 份虚构简历、7 条 HR 审核、4 条推荐、3 条部门反馈。前端岗位的 2 个名额仅是演示数值；产品岗位名额留空，用于展示“缺口待补”。',
        '',
        'DeepSeek 密钥未写入此文件或数据库。模型评分仍须在本机配置密钥后由招聘专员主动发起；当前不存在预造的 AI 分数。',
        '',
    ]
    TEMP_CREDENTIALS.write_text('\n'.join(content), encoding='utf-8')
    export_candidates = snapshot()['candidates']
    TEMP_DATABASE.replace(DATABASE)
    TEMP_CREDENTIALS.replace(CREDENTIALS)
    resume_dir = ROOT / '虚构演示简历'
    resume_dir.mkdir(exist_ok=True)
    for candidate in export_candidates:
        (resume_dir / candidate['fileName']).write_text(candidate['text'] + '\n', encoding='utf-8')
    print('演示数据建立完成：6 个账号、2 个岗位、12 份简历、7 条人工审核、4 条推荐、3 条部门反馈。')
    print('登录信息已保存到：' + str(CREDENTIALS))
except Exception:
    if TEMP_DATABASE.exists():
        TEMP_DATABASE.unlink()
    if TEMP_CREDENTIALS.exists():
        TEMP_CREDENTIALS.unlink()
    raise
