import base64
import importlib.util
import io
import json
import os
import socket
import unittest
import urllib.error
import zipfile
from unittest.mock import Mock, patch
import deepseek_server as service


class ScoringTests(unittest.TestCase):
    def payload(self):
        return {'consent': True, 'job': {'name': '测试岗位', 'requirements': ['组件开发'], 'bonus': ['性能分析']},
                'resume': '负责组件开发。参与性能分析。', 'version': 'test-v1'}

    def response(self, items, finish='stop'):
        return io.BytesIO(json.dumps({'model': 'test-model', 'choices': [{'finish_reason': finish,
              'message': {'content': json.dumps({'items': items, 'summary': '测试返回', 'questions': []})}}]}).encode())

    def rows(self):
        return [{'group': 'core', 'index': 0, 'score': 90, 'quote': '负责组件开发。', 'reason': '对应要求'},
                {'group': 'bonus', 'index': 0, 'score': 70, 'quote': '参与性能分析。', 'reason': '部分对应'}]

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_live_request_structure_and_server_calculation(self):
        def transport(request, timeout):
            self.assertEqual(request.full_url, 'https://api.deepseek.com/chat/completions')
            body = json.loads(request.data)
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertNotIn('test-only-key', request.data.decode())
            return self.response(self.rows())
        result = service.analyze(self.payload(), transport)
        self.assertEqual(result['score'], 86)
        self.assertEqual(result['version'], 'test-v1')
        self.assertEqual(len(result['resumeHash']), 64)
        self.assertNotIn('resume', result)

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_unsupported_quote_does_not_become_zero_or_total_score(self):
        rows = self.rows()
        rows[0]['quote'] = '原文并不存在的优秀经历'
        result = service.analyze(self.payload(), lambda *a, **k: self.response(rows))
        self.assertIsNone(result['score'])
        self.assertIsNone(result['coreScore'])
        self.assertIsNone(result['items'][0]['score'])
        self.assertEqual(result['items'][0]['quote'], '')
        self.assertEqual(result['evidenceCount'], 1)

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_missing_condition_fails_instead_of_making_up_score(self):
        with self.assertRaises(service.RequestProblem):
            service.analyze(self.payload(), lambda *a, **k: self.response(self.rows()[:1]))

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_extra_condition_row_is_rejected(self):
        rows = self.rows() + [{'group': 'core', 'index': 1, 'score': 90, 'quote': '负责组件开发。', 'reason': '模型自行增加的条件'}]
        with self.assertRaises(service.RequestProblem):
            service.analyze(self.payload(), lambda *a, **k: self.response(rows))

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_truncated_model_output_not_accepted(self):
        with self.assertRaises(service.RequestProblem):
            service.analyze(self.payload(), lambda *a, **k: self.response(self.rows(), 'length'))

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_no_consent_makes_no_remote_call(self):
        payload = self.payload()
        payload['consent'] = False
        def forbidden(*a, **k):
            self.fail('must not invoke transport without consent')
        with self.assertRaises(service.RequestProblem):
            service.analyze(payload, forbidden)

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''})
    def test_missing_key_is_explicit(self):
        with self.assertRaisesRegex(service.RequestProblem, 'API Key'):
            service.analyze(self.payload())

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_remote_error_does_not_echo_key_or_upstream_body(self):
        def transport(*args, **kwargs):
            raise urllib.error.HTTPError('https://api.deepseek.com', 401, 'test-only-key', {}, None)
        with self.assertRaises(service.RequestProblem) as result:
            service.analyze(self.payload(), transport)
        self.assertNotIn('test-only-key', str(result.exception))
        self.assertIn('无效', str(result.exception))

    def test_txt_and_docx_extract_locally(self):
        text = '测试材料：负责组件开发。'
        result = service.extract({'name': 'test.txt', 'content': base64.b64encode(text.encode()).decode()})
        self.assertEqual(result['text'], text)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>组件开发经历</w:t></w:r></w:p></w:body></w:document>')
        result = service.extract({'name': 'test.docx', 'content': base64.b64encode(data.getvalue()).decode()})
        self.assertEqual(result['text'], '组件开发经历')

    def test_bad_file_does_not_succeed(self):
        for name, content in [('empty.txt', ''), ('bad.docx', 'broken'), ('a.exe', 'unsupported')]:
            with self.subTest(name=name), self.assertRaises(service.RequestProblem):
                service.extract({'name': name, 'content': base64.b64encode(content.encode()).decode()})

    def test_empty_docx_reports_missing_text(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t></w:t></w:r></w:p></w:body></w:document>')
        with self.assertRaisesRegex(service.RequestProblem, '未提取到文字'):
            service.extract({'name': 'empty.docx', 'content': base64.b64encode(data.getvalue()).decode()})

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), '当前解释器未安装 pypdf，PDF 提取不可用')
    def test_scanned_pdf_reports_no_ocr(self):
        from pypdf import PdfWriter
        data = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(data)
        with self.assertRaisesRegex(service.RequestProblem, 'OCR'):
            service.extract({'name': 'blank.pdf', 'content': base64.b64encode(data.getvalue()).decode()})

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_remote_payment_limit_timeout_and_garbage_are_explicit(self):
        def http_error(code):
            def transport(*args, **kwargs):
                raise urllib.error.HTTPError('https://api.deepseek.com', code, 'test-only-key', {}, None)
            return transport
        for code, word in ((402, '余额'), (429, '受限')):
            with self.subTest(code=code), self.assertRaisesRegex(service.RequestProblem, word):
                service.analyze(self.payload(), http_error(code))
        def timeout(*args, **kwargs):
            raise socket.timeout()
        with self.assertRaisesRegex(service.RequestProblem, '超时'):
            service.analyze(self.payload(), timeout)
        with self.assertRaisesRegex(service.RequestProblem, '无法解析'):
            service.analyze(self.payload(), lambda *a, **k: io.BytesIO(b'not-json'))

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only-key'})
    def test_result_has_no_automatic_grade_or_decision(self):
        result = service.analyze(self.payload(), lambda *a, **k: self.response(self.rows()))
        self.assertNotIn('grade', result)
        self.assertNotIn('decision', result)
        self.assertEqual(result['evidenceCount'], 2)
        self.assertEqual(result['conditionCount'], 2)
        self.assertTrue(all(item['status'] == '有原文证据，仍待核实' for item in result['items']))

    def test_file_larger_than_10_mb_is_rejected(self):
        oversized = b'a' * (10 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(service.RequestProblem, '10 MB'):
            service.extract({'name': 'too-large.txt', 'content': base64.b64encode(oversized).decode()})

    @unittest.skipUnless(importlib.util.find_spec('pypdf'), '当前解释器未安装 pypdf，PDF 提取不可用')
    def test_pdf_over_50_pages_is_rejected(self):
        from pypdf import PdfWriter
        data = io.BytesIO()
        writer = PdfWriter()
        for _ in range(51):
            writer.add_blank_page(width=100, height=100)
        writer.write(data)
        with self.assertRaisesRegex(service.RequestProblem, '50 页'):
            service.extract({'name': 'too-many.pdf', 'content': base64.b64encode(data.getvalue()).decode()})

    def test_text_longer_than_limit_is_rejected_not_truncated(self):
        text = '虚构' * 30001
        with self.assertRaisesRegex(service.RequestProblem, '60000'):
            service.extract({'name': 'too-long.txt', 'content': base64.b64encode(text.encode()).decode()})

    def test_cross_site_and_host_rejected(self):
        handler = object.__new__(service.Handler)
        for headers in [{'Host': 'evil.example'}, {'Host': f'127.0.0.1:{service.PORT}', 'Origin': 'https://evil.example'},
                        {'Host': f'localhost:{service.PORT}', 'Sec-Fetch-Site': 'cross-site'}]:
            handler.headers = headers
            with self.assertRaises(service.RequestProblem):
                handler.check_origin()

    def test_post_without_local_token_is_rejected(self):
        handler = object.__new__(service.Handler)
        handler.headers = {'Content-Type': 'application/json'}
        handler.check_origin = lambda: None
        handler.reply = Mock()
        handler.do_POST()
        self.assertEqual(handler.reply.call_args.args[0], 403)
        self.assertIn('本机会话', handler.reply.call_args.args[1]['error'])

    def analyze_handler(self):
        body = json.dumps({'candidateId': 'c1', 'consent': True}).encode()
        handler = object.__new__(service.Handler)
        handler.headers = {'X-Local-Token': service.TOKEN, 'Content-Type': 'application/json',
                           'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.connection = Mock()
        handler.path = '/api/analyze'
        handler.check_origin = lambda: None
        handler.identity = lambda: {'id': 'u1', 'role': 'hr', 'name': '测试HR'}
        handler.reply = Mock()
        return handler

    def test_remote_failure_records_status_but_precondition_failure_does_not(self):
        context = {'candidateId': 'c1', 'jobId': 'j1', 'version': 'v1', 'resume': '虚构正文'}
        for status, message, should_record in ((502, 'DeepSeek 账户余额不足。', True),
                                               (504, 'DeepSeek 响应超时。', True),
                                               (503, '尚未配置 DeepSeek API Key。', False),
                                               (400, '请先确认发送。', False)):
            with self.subTest(status=status), \
                    patch.object(service.accounts, 'require'), \
                    patch.object(service.accounts, 'analysis_context', return_value=context), \
                    patch.object(service.accounts, 'save_analysis') as saved, \
                    patch.object(service, 'analyze', side_effect=service.RequestProblem(message, status)), \
                    patch.object(service.accounts, 'record_analysis_failure') as recorded:
                handler = self.analyze_handler()
                handler.do_POST()
                self.assertEqual(handler.reply.call_args.args[0], status)
                if should_record:
                    recorded.assert_called_once()
                else:
                    recorded.assert_not_called()
                saved.assert_not_called()


if __name__ == '__main__':
    unittest.main()
