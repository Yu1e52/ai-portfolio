import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch
import recruitment_store as store


class RolesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent, prefix='.test-accounts-')
        self.patch = patch.object(store, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.patch.start()
        store.SESSIONS.clear()
        store.FAILURES.clear()
        self.admin = store.setup({'username': 'test.admin', 'name': '测试管理员', 'password': 'OnlyForUnitTests_2026'})
        self.manager = self.create('test.manager', '经理A', 'manager')
        self.manager2 = self.create('test.manager2', '经理B', 'manager')
        self.hr = self.create('test.hr', '专员A', 'hr')
        self.hr2 = self.create('test.hr2', '专员B', 'hr')
        self.dept = self.create('test.tech', '技术部门', 'department', '技术部')
        self.other_dept = self.create('test.product', '产品部门', 'department', '产品部')
        store.mutate(self.manager, '/api/jobs', {'name': '测试岗位', 'department': '技术部', 'requirements': ['组件开发'], 'bonus': [], 'source': '测试材料', 'headcount': None})
        self.job = store.data(self.manager)['jobs'][0]
        store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr['id']})
        store.mutate(self.hr, '/api/candidates', {'jobId': self.job['id'], 'name': '测试候选材料', 'text': '虚构测试材料：负责组件开发。'})
        self.candidate = store.data(self.hr)['candidates'][0]

    def tearDown(self):
        self.patch.stop()
        assert Path(self.temp.name).resolve().is_relative_to(Path(__file__).resolve().parent)
        self.temp.cleanup()

    def create(self, username, name, role, department=''):
        store.mutate(self.admin, '/api/users', {'username': username, 'name': name, 'role': role, 'department': department, 'password': 'OnlyForUnitTests_2026'})
        return next(u for u in store.users(self.admin) if u['username'] == username)

    def pass_and_refer(self):
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': self.job['versions'][-1]['id'], 'decision': 'pass', 'match': 'yes', 'reason': '测试人工核实通过'})
        store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        return store.data(self.hr)['referrals'][0]

    def test_admin_has_no_resume_or_job_access(self):
        view = store.data(self.admin)
        self.assertEqual(view['candidates'], [])
        self.assertEqual(view['jobs'], [])
        with self.assertRaises(store.Problem):
            store.analysis_context(self.admin, self.candidate['id'])

    def test_duplicate_material_is_flagged_and_retained(self):
        store.mutate(self.hr, '/api/candidates', {'jobId': self.job['id'], 'name': '同正文测试', 'text': self.candidate['text']})
        materials = store.data(self.hr)['candidates']
        self.assertEqual(len(materials), 2)
        self.assertTrue(materials[-1]['duplicate'])

    def test_unassigned_hr_and_other_manager_cannot_read_or_write(self):
        self.assertEqual(store.data(self.hr2)['candidates'], [])
        self.assertEqual(store.data(self.manager2)['jobs'], [])
        with self.assertRaises(store.Problem):
            store.analysis_context(self.hr2, self.candidate['id'])
        with self.assertRaises(store.Problem):
            store.mutate(self.manager2, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})

    def test_department_only_receives_explicit_recommendation(self):
        self.assertEqual(store.data(self.dept)['candidates'], [])
        ref = self.pass_and_refer()
        self.assertEqual(len(store.data(self.dept)['candidates']), 1)
        self.assertEqual(store.data(self.other_dept)['candidates'], [])
        with self.assertRaises(store.Problem):
            store.mutate(self.other_dept, '/api/feedback', {'referralId': ref['id'], 'stage': '面试后', 'match': 'yes', 'reason': '越权测试'})

    def test_reassignment_revokes_previous_hr_scope_and_keeps_history(self):
        self.pass_and_refer()
        store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})
        self.assertEqual(store.data(self.hr)['candidates'], [])
        with self.assertRaises(store.Problem):
            store.analysis_context(self.hr, self.candidate['id'])
        new_view = store.data(self.hr2)
        self.assertEqual(len(new_view['candidates'][0]['reviews']), 1)
        self.assertEqual(len(new_view['referrals']), 1)

    def test_disabled_user_session_immediately_invalid(self):
        sid, _ = store.login({'username': 'test.hr', 'password': 'OnlyForUnitTests_2026'})
        self.assertIsNotNone(store.session(sid))
        store.mutate(self.admin, '/api/users/status', {'id': self.hr['id'], 'enabled': False})
        self.assertIsNone(store.session(sid))
        with self.assertRaises(store.Problem):
            store.login({'username': 'test.hr', 'password': 'OnlyForUnitTests_2026'})

    def test_demo_switch_is_explicit_and_limited_to_demo_accounts(self):
        demo_hr = self.create('demo.hr.tech', '演示专员', 'hr')
        with patch.dict(os.environ, {'RECRUITMENT_DEMO_MODE': '0'}):
            self.assertEqual(store.demo_users(), [])
            with self.assertRaises(store.Problem):
                store.demo_switch('demo.hr.tech')
        with patch.dict(os.environ, {'RECRUITMENT_DEMO_MODE': '1'}):
            self.assertEqual([u['username'] for u in store.demo_users()], ['demo.hr.tech'])
            sid, switched = store.demo_switch('demo.hr.tech')
            self.assertEqual(switched['id'], demo_hr['id'])
            self.assertEqual(store.data(store.session(sid))['jobs'], [])
            with self.assertRaises(store.Problem):
                store.demo_switch('test.admin')
            store.mutate(self.admin, '/api/users/status', {'id': demo_hr['id'], 'enabled': False})
            with self.assertRaises(store.Problem):
                store.demo_switch('demo.hr.tech')
    def test_new_requirement_does_not_release_to_department_or_invalidate_history(self):
        ref = self.pass_and_refer()
        store.mutate(self.manager, '/api/jobs', {'id': self.job['id'], 'name': '测试岗位', 'department': '技术部', 'requirements': ['新版本条件'], 'bonus': [], 'source': '变更测试', 'headcount': None})
        view = store.data(self.dept)
        self.assertEqual(len(view['jobs'][0]['versions']), 1)
        self.assertEqual(view['jobs'][0]['versions'][0]['id'], ref['version'])
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        self.assertEqual(len(store.data(self.hr)['candidates'][0]['reviews']), 1)

    def test_score_return_cannot_write_after_assignment_change(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})
        with self.assertRaises(store.Problem):
            store.save_analysis(self.hr, context, {'version': context['version'], 'score': 90})
        self.assertEqual(store.data(self.hr2)['candidates'][0]['analyses'], [])

    def test_cannot_create_user_or_self_disable_without_permission(self):
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/users', {'username': 'evil', 'name': 'test', 'role': 'admin', 'password': 'OnlyForUnitTests_2026'})
        with self.assertRaises(store.Problem):
            store.mutate(self.admin, '/api/users/status', {'id': self.admin['id'], 'enabled': False})


    def test_analysis_cannot_save_after_new_requirement_version(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.mutate(self.manager, '/api/jobs', {'id': self.job['id'], 'name': '测试岗位', 'department': '技术部', 'requirements': ['再次变更的条件'], 'bonus': [], 'source': '分析期间变更', 'headcount': None})
        with self.assertRaises(store.Problem):
            store.save_analysis(self.hr, context, {'version': context['version'], 'score': 88})
        self.assertEqual(store.data(self.hr)['candidates'][0]['analyses'], [])

    def test_user_directory_is_limited_to_roles_that_need_it(self):
        self.assertEqual(store.users(self.hr), [])
        self.assertEqual(store.users(self.dept), [])
        self.assertEqual({u['role'] for u in store.users(self.manager)}, {'hr', 'department'})
        self.assertEqual(len(store.users(self.admin)), 7)

    def test_batch_import_id_is_stored_and_validated(self):
        batch = '8f2f0d88-batch-2026'
        store.mutate(self.hr, '/api/candidates', {'jobId': self.job['id'], 'name': '批次材料', 'text': '虚构批次正文', 'batchId': batch})
        material = next(c for c in store.data(self.hr)['candidates'] if c['name'] == '批次材料')
        self.assertEqual(material['batchId'], batch)
        self.assertIn(batch, material['events'][0]['text'])
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/candidates', {'jobId': self.job['id'], 'name': '坏批次', 'text': '另一份虚构正文', 'batchId': 'bad id!'})

    def test_duplicate_referral_and_stale_review_are_rejected(self):
        old_version = self.job['versions'][-1]['id']
        self.pass_and_refer()
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        self.assertEqual(len(store.data(self.hr)['referrals']), 1)
        store.mutate(self.manager, '/api/jobs', {'id': self.job['id'], 'name': '测试岗位', 'department': '技术部', 'requirements': ['过期审核测试'], 'bonus': [], 'source': '版本测试', 'headcount': None})
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': old_version, 'decision': 'pass', 'match': 'yes', 'reason': '旧版本审核'})

    def test_invalid_headcount_is_rejected(self):
        with self.assertRaises(store.Problem):
            store.mutate(self.manager, '/api/jobs', {'id': self.job['id'], 'name': '测试岗位', 'department': '技术部', 'requirements': ['组件开发'], 'bonus': [], 'source': '名额校验', 'headcount': -1})

    def test_conflicting_department_opinions_are_retained(self):
        ref = self.pass_and_refer()
        for opinion in ('yes', 'no'):
            store.mutate(self.dept, '/api/feedback', {'referralId': ref['id'], 'stage': '面试后', 'match': opinion, 'reason': '虚构部门意见 ' + opinion})
        store.mutate(self.dept, '/api/feedback', {'referralId': ref['id'], 'stage': '试岗后', 'match': 'unknown', 'reason': '试岗后继续观察'})
        feedbacks = store.data(self.dept)['feedbacks']
        self.assertEqual([(f['stage'], f['match']) for f in feedbacks],
                         [('面试后', 'yes'), ('面试后', 'no'), ('试岗后', 'unknown')])

    def test_setup_is_one_time_and_department_role_needs_department(self):
        with self.assertRaisesRegex(store.Problem, '已初始化'):
            store.setup({'username': 'second.admin', 'name': '第二管理员', 'password': 'OnlyForUnitTests_2026'})
        with self.assertRaises(store.Problem):
            store.mutate(self.admin, '/api/users', {'username': 'test.nondept', 'name': '无部门账号', 'role': 'department', 'department': '', 'password': 'OnlyForUnitTests_2026'})
        self.assertNotIn('test.nondept', [u['username'] for u in store.users(self.admin)])

    def test_login_lockout_after_five_failures(self):
        for _ in range(5):
            with self.assertRaises(store.Problem) as blocked:
                store.login({'username': 'test.hr', 'password': 'wrong-password'})
            self.assertEqual(blocked.exception.status, 401)
        with self.assertRaises(store.Problem) as limited:
            store.login({'username': 'test.hr', 'password': 'OnlyForUnitTests_2026'})
        self.assertEqual(limited.exception.status, 429)

    def test_job_validation_rejects_invalid_input_without_saving(self):
        base = {'name': '校验岗位', 'department': '技术部', 'requirements': ['组件开发'], 'bonus': [], 'source': '校验测试', 'headcount': None}
        for change in ({'department': '尚不存在部门'}, {'requirements': []}, {'requirements': ['条件'] * 41},
                       {'requirements': ['长' * 501]}, {'headcount': '3'}, {'department': '产品部'}):
            payload = dict(base, **change)
            if change.get('department') == '产品部':
                payload['id'] = self.job['id']
            with self.subTest(change=change), self.assertRaises(store.Problem):
                store.mutate(self.manager, '/api/jobs', payload)
        jobs = store.data(self.manager)['jobs']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['department'], '技术部')
        self.assertEqual(len(jobs[0]['versions']), 1)

    def test_assignment_requires_enabled_hr_and_keeps_history(self):
        store.mutate(self.admin, '/api/users/status', {'id': self.hr2['id'], 'enabled': False})
        with self.assertRaises(store.Problem):
            store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})
        store.mutate(self.admin, '/api/users/status', {'id': self.hr2['id'], 'enabled': True})
        store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})
        job = store.data(self.manager)['jobs'][0]
        self.assertEqual(job['hrId'], self.hr2['id'])
        self.assertEqual([a['to'] for a in job['assignments']], ['专员A', '专员B'])
        self.assertEqual(job['assignments'][-1]['from'], '专员A')

    def test_review_validation_manual_pass_without_ai_and_history(self):
        version = self.job['versions'][-1]['id']
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'pass', 'match': 'yes', 'reason': ''})
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'hire', 'match': 'yes', 'reason': '非法枚举'})
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'pass', 'match': 'yes', 'reason': '无 AI 结果时人工通过'})
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'more', 'match': 'partial', 'reason': '需要补充材料'})
        reviews = store.data(self.hr)['candidates'][0]['reviews']
        self.assertEqual([r['decision'] for r in reviews], ['pass', 'more'])
        self.assertIsNone(reviews[0]['analysisId'])
        self.assertEqual(store.data(self.hr)['candidates'][0]['analyses'], [])

    def test_low_ai_score_can_still_be_manually_passed(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.save_analysis(self.hr, context, {'version': context['version'], 'score': 5, 'coreScore': 5})
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': context['version'], 'decision': 'pass', 'match': 'yes', 'reason': '人工核实后通过'})
        candidate = store.data(self.hr)['candidates'][0]
        self.assertEqual(candidate['analyses'][0]['score'], 5)
        self.assertEqual(candidate['reviews'][0]['decision'], 'pass')
        self.assertEqual(candidate['analyses'][0]['score'], 5)

    def test_referral_preconditions_version_and_department(self):
        version = self.job['versions'][-1]['id']
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'fail', 'match': 'no', 'reason': '人工判断未通过'})
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        store.mutate(self.hr, '/api/reviews', {'candidateId': self.candidate['id'], 'version': version, 'decision': 'pass', 'match': 'yes', 'reason': '复核后明确通过'})
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '产品部'})
        store.mutate(self.hr, '/api/referrals', {'candidateId': self.candidate['id'], 'department': '技术部'})
        referral = store.data(self.hr)['referrals'][0]
        latest_review = store.data(self.hr)['candidates'][0]['reviews'][-1]
        self.assertEqual(referral['version'], version)
        self.assertEqual(referral['reviewId'], latest_review['id'])
        self.assertEqual(referral['department'], '技术部')

    def test_feedback_enums_outcome_and_hired_date(self):
        ref = self.pass_and_refer()
        base = {'referralId': ref['id'], 'stage': '面试后', 'match': 'yes', 'reason': '虚构反馈', 'outcome': '', 'confirmed': False, 'occurred': ''}
        for change in ({'stage': '终面'}, {'match': 'strong'}, {'outcome': '待定'}):
            with self.subTest(change=change), self.assertRaises(store.Problem):
                store.mutate(self.dept, '/api/feedback', dict(base, **change))
        with self.assertRaises(store.Problem):
            store.mutate(self.dept, '/api/feedback', dict(base, stage='试岗后', outcome='已入职', confirmed=True, occurred=''))
        with self.assertRaises(store.Problem):
            store.mutate(self.dept, '/api/feedback', dict(base, confirmed='yes'))
        store.mutate(self.dept, '/api/feedback', dict(base, stage='试岗后', outcome='已入职', confirmed=True, occurred='2026-10-24'))
        feedback = store.data(self.dept)['feedbacks'][0]
        self.assertEqual(feedback['outcome'], '已入职')
        self.assertEqual(feedback['occurred'], '2026-10-24')

    def test_repeated_analysis_appends_history_without_overwriting(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        first = store.save_analysis(self.hr, context, {'version': context['version'], 'score': 10, 'resumeHash': 'a' * 64})
        second = store.save_analysis(self.hr, context, {'version': context['version'], 'score': 20, 'resumeHash': 'a' * 64})
        analyses = store.data(self.hr)['candidates'][0]['analyses']
        self.assertEqual([a['score'] for a in analyses], [10, 20])
        self.assertEqual([a['version'] for a in analyses], [context['version'], context['version']])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(store.data(self.hr)['candidates'][0]['analysisStatus'], 'scored')

    def test_failed_analysis_is_recorded_without_overwriting_history(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.save_analysis(self.hr, context, {'version': context['version'], 'score': 55})
        store.record_analysis_failure(self.hr, context, 'DeepSeek 响应超时，本次未保存评分。')
        candidate = store.data(self.hr)['candidates'][0]
        self.assertEqual(candidate['analysisStatus'], 'failed')
        self.assertIn('超时', candidate['analysisError'])
        self.assertEqual(len(candidate['analyses']), 1)
        self.assertEqual(candidate['analyses'][0]['score'], 55)
        self.assertTrue(any('评分失败' in event['text'] for event in candidate['events']))

    def test_department_does_not_receive_ai_failure_details(self):
        self.pass_and_refer()
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.record_analysis_failure(self.hr, context, 'DeepSeek 响应超时。')
        material = store.data(self.dept)['candidates'][0]
        self.assertNotIn('analysisStatus', material)
        self.assertNotIn('analysisError', material)

    def test_failure_status_is_not_written_after_reassignment(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.mutate(self.manager, '/api/assign', {'jobId': self.job['id'], 'hrId': self.hr2['id']})
        with self.assertRaises(store.Problem):
            store.record_analysis_failure(self.hr, context, 'DeepSeek 响应超时。')
        candidate = store.data(self.manager)['candidates'][0]
        self.assertEqual(candidate.get('analysisStatus'), 'unscored')

    def test_tampered_identifiers_are_rejected(self):
        version = self.job['versions'][-1]['id']
        with self.assertRaisesRegex(store.Problem, '不存在或无权访问'):
            store.analysis_context(self.hr, 'tampered-material-id')
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/reviews', {'candidateId': 'tampered-material-id', 'version': version, 'decision': 'pass', 'match': 'yes', 'reason': '篡改测试'})
        with self.assertRaisesRegex(store.Problem, '不存在或无权访问'):
            store.mutate(self.manager, '/api/assign', {'jobId': 'tampered-job-id', 'hrId': self.hr['id']})

    def test_analysis_write_rejected_after_account_disabled(self):
        context = store.analysis_context(self.hr, self.candidate['id'])
        store.mutate(self.admin, '/api/users/status', {'id': self.hr['id'], 'enabled': False})
        with self.assertRaises(store.Problem):
            store.save_analysis(self.hr, context, {'version': context['version'], 'score': 90})
        self.assertEqual(store.data(self.manager)['candidates'][0]['analyses'], [])

    def test_import_requires_assigned_job_and_nonempty_text(self):
        with self.assertRaises(store.Problem):
            store.mutate(self.hr2, '/api/candidates', {'jobId': self.job['id'], 'name': '越权材料', 'text': '虚构正文'})
        with self.assertRaises(store.Problem):
            store.mutate(self.hr, '/api/candidates', {'jobId': self.job['id'], 'name': '空正文', 'text': '   '})
        self.assertEqual(len(store.data(self.hr)['candidates']), 1)

    def test_password_not_plaintext_and_data_survives_new_session(self):
        sid, _ = store.login({'username': 'test.hr', 'password': 'OnlyForUnitTests_2026'})
        store.SESSIONS.clear()
        self.assertIsNone(store.session(sid))
        new_sid, _ = store.login({'username': 'test.hr', 'password': 'OnlyForUnitTests_2026'})
        self.assertIsNotNone(store.session(new_sid))
        self.assertEqual(len(store.data(store.session(new_sid))['candidates']), 1)
        raw = store.DB_PATH.read_bytes()
        self.assertNotIn(b'OnlyForUnitTests_2026', raw)
        self.assertNotIn(b'PBKDF2', raw)


if __name__ == '__main__':
    unittest.main()
