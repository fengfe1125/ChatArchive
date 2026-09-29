import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Engine'))
from native_backup import Snapshot
from native_server import NativeService

class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        source = base / 'source'
        (source / 'projects/p').mkdir(parents=True)
        self.body = ('正文🙂 **完整**\n' * 12000) + '最后一个字'
        self.attachment = '附件原文🙂\n' * 7000
        records = [{'type':'user','message':{'content':'question'}},
                   {'type':'assistant','message':{'content':self.body}}]
        (source / 'projects/p/chat.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
        with zipfile.ZipFile(source / 'conversations-000.zip', 'w') as z:
            z.writestr('conversations.json', json.dumps([{'uuid':'chat','chat_messages':[
                {'sender':'human','text':'question'}, {'sender':'assistant','text':self.body,
                 'attachments':[{'file_name':'large.txt','extracted_content':self.attachment}]}]}]))
        dest = base / 'out'; dest.mkdir()
        snap = Snapshot([str(source)], str(dest)); snap.run()
        service = NativeService(); service.open_archive({'path':str(snap.root)})
        self.archive = service.archive
        self.read_page = getattr(self.archive, "reading_messages", self.archive.messages)

    def test_native_pages_are_bounded_and_lossless_for_chat_and_code(self):
        for row in self.archive.sessions.values():
            offset = 0; body = ''; attachments = ''; pages = 0
            while offset is not None:
                page = self.read_page(row['id'], offset)
                self.assertLessEqual(len(page['items']), 8)
                for item in page['items']:
                    self.assertLessEqual(len(item['text']), 12000)
                    if item['role'] == 'assistant': body += item['text']
                    for media in item.get('media', []):
                        self.assertLessEqual(len(media.get('text', '')), 12000)
                        attachments += media.get('text', '')
                following = page['next_offset']
                self.assertTrue(following is None or following > offset)
                offset = following; pages += 1
                self.assertLess(pages, 100)
            self.assertEqual(body, self.body)
            self.assertEqual(attachments, self.attachment if row['source'] == 'account' else '')
            # Existing export APIs still receive full original messages.
            self.assertEqual(list(self.archive.messages_all(row['id']))[1]['text'], self.body)

    def test_click_and_next_page_do_not_reparse_source(self):
        with patch('archive_core._code_events', side_effect=AssertionError('reparsed source')), \
             patch.object(self.archive, '_account_messages', side_effect=AssertionError('reparsed cache')):
            for row in self.archive.sessions.values():
                first = self.read_page(row['id'])
                self.read_page(row['id'], first['next_offset'])

    def test_invalid_source_cannot_be_read_from_presentation_index(self):
        row = next(iter(self.archive.sessions.values()))
        row['valid_hash'] = False
        with self.assertRaisesRegex(ValueError, '哈希'):
            self.read_page(row['id'])
