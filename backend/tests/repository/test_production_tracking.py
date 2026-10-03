"""Tracking metadata remains optional and round-trips through the existing store."""
import tempfile
import unittest
from pathlib import Path

from features.production import production_store as store, ref_media
from tests.repository.test_production_via_repository import _patch_path
from tests.repository._backend import setUpModule, tearDownModule  # noqa: F401


class ProductionTrackingTests(unittest.TestCase):
    def test_cleared_badges_roundtrip_without_losing_tasks_or_content(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_path(Path(directory) / 'production.json'):
                data = store.default_schema()
                seq = store.add_sequence(data, 'SEQ0010')
                shot = store.add_shot(data, seq['id'], 'SHOT0010')
                asset = store.add_asset(data, 'CHAR', 'HERO')
                for entity in [seq, shot, asset]:
                    task = store.add_task(entity, 'ANIM', ['ANIM'])
                    task['known_subtasks'] = ['BLOCK']
                    store.update_task_detail(entity, 'ANIM', {'status': '', 'assignee': 'TOM', 'notes': 'Keep'})
                    store.update_task_detail(entity, 'ANIM|BLOCK', {'status': '', 'comments': [{'id': 'c', 'text': 'Keep'}]})
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                loaded = store.load_production('TRACKING_TEST')
                self.assertEqual(loaded, data)
                for entity in [loaded['sequences'][0], loaded['shots'][0], loaded['assets'][0]]:
                    self.assertEqual(entity['task_details']['ANIM']['status'], '')
                    self.assertEqual(entity['task_details']['ANIM']['assignee'], 'TOM')
                    self.assertEqual(entity['tasks'][0]['known_subtasks'], ['BLOCK'])

    def test_shot_tracking_and_thumbnail_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with _patch_path(root / 'production.json'):
                data = store.default_schema()
                seq = store.add_sequence(data, 'SEQ0010')
                shot = store.add_shot(data, seq['id'], 'SHOT0020')
                assets = [store.add_asset(data, 'CHAR', 'HERO'), store.add_asset(data, 'ENV', 'SET')]
                shot['assets'] = [{'id': asset['id'], 'ref': asset['name']} for asset in assets]
                shot['label'] = 'Opening'
                for token, status in [('LAYOUT', 'APPROVED'), ('ANIM', 'RTK')]:
                    store.add_task(shot, token, [token])
                    store.update_task_detail(shot, token, {'status': status, 'notes': 'Keep me'})
                shot['dependencies'] = [{'entity_id': assets[0]['id'], 'task': 'RIG'}]
                rel = f"_production/thumbnails/{shot['id']}"
                deposited = ref_media.deposit(root, rel, 'preview.png', b'preview-image-bytes')
                shot['thumbnail'] = {'rel_path': rel, 'file': deposited['version'] + deposited['ext']}
                data['tracking'] = {'departments': [{'id': 'anim', 'name': 'Animation', 'scope': 'shot', 'active': True, 'fixed': True, 'task_tokens': ['ANIM'], 'statuses': ['TODO', 'WIP', 'RTK', 'APPROVED'], 'depends_on': ['layout']}]}
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                loaded = store.load_production('TRACKING_TEST')
                self.assertEqual(loaded, data)
                self.assertEqual(len(loaded['shots'][0]['assets']), 2)
                self.assertEqual(loaded['shots'][0]['task_details']['ANIM']['status'], 'RTK')
                thumb = loaded['shots'][0]['thumbnail']
                self.assertEqual(ref_media.resolve_file(root, thumb['rel_path'], thumb['file']).read_bytes(), b'preview-image-bytes')

    def test_legacy_empty_projects_need_no_tracking_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_path(Path(directory) / 'production.json'):
                data = store.default_schema()
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                loaded = store.load_production('TRACKING_TEST')
                self.assertEqual(loaded['shots'], [])
                self.assertNotIn('tracking', loaded)

    def test_artist_assignments_roundtrip_with_notes_and_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_path(Path(directory) / 'production.json'):
                data = store.default_schema()
                seq = store.add_sequence(data, 'SEQ0010')
                shot = store.add_shot(data, seq['id'], 'SHOT0010')
                asset = store.add_asset(data, 'CHAR', 'HERO')
                for entity in [seq, shot, asset]:
                    store.add_task(entity, 'ANIM', ['ANIM'])
                    store.update_task_detail(entity, 'ANIM', {'status': 'WIP', 'assignee': 'TOM', 'notes': 'Keep'})
                    store.update_task_detail(entity, 'ANIM|BLOCK', {'status': 'RTK', 'assignee': 'ANTOINE'})
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                loaded = store.load_production('TRACKING_TEST')
                self.assertEqual(loaded, data)
                for entity in [loaded['sequences'][0], loaded['shots'][0], loaded['assets'][0]]:
                    self.assertEqual(entity['task_details']['ANIM']['assignee'], 'TOM')
                    self.assertEqual(entity['task_details']['ANIM|BLOCK']['assignee'], 'ANTOINE')

    def test_department_configuration_preserves_tasks_reviews_and_existing_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with _patch_path(root / 'production.json'):
                data = store.default_schema()
                asset = store.add_asset(data, 'CHAR', 'HERO')
                store.add_task(asset, 'RIG', ['RIG'])
                store.update_task_detail(asset, 'RIG', {'status': 'APPROVED', 'assignee': 'TOM'})
                existing = root / 'assets' / 'char' / 'HERO' / 'rig' / 'keep.txt'
                existing.parent.mkdir(parents=True)
                existing.write_text('Keep published files', encoding='utf-8')
                data['tracking'] = {'departments': [{'id': 'new', 'name': 'New dept', 'scope': 'asset', 'fixed': True, 'active': True, 'task_tokens': ['NEW'], 'statuses': ['TODO'], 'depends_on': []}]}
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                self.assertEqual([task['name'] for task in asset['tasks']], ['RIG'])
                self.assertFalse((existing.parent.parent / 'new').exists())
                data['tracking']['departments'] = []
                self.assertTrue(store.save_production('TRACKING_TEST', data))
                loaded = store.load_production('TRACKING_TEST')
                self.assertEqual(loaded['tracking']['departments'], [])
                self.assertEqual(loaded['assets'][0]['task_details']['RIG']['status'], 'APPROVED')
                self.assertEqual(existing.read_text(encoding='utf-8'), 'Keep published files')
