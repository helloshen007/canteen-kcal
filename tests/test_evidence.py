"""临时合成证据验证打包规则，不调用 API，也不产生实验指标。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.export_evidence import export
from vlm.run_vlm import to_result


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.results = self.root / 'predictions'
        self.output = self.root / 'evidence.zip'
        (self.root / 'data').mkdir()
        (self.root / 'data/ground_truth.csv').write_text(
            'image_id,split,visible_dishes\ndish_1,test,watermelon:10\n', encoding='utf-8')
        (self.root / 'data/ingredient_nutrition.csv').write_text(
            'name,kcal,protein,fat,carb\nwatermelon,30,1,0,6\n', encoding='utf-8')
        (self.root / 'data/dish_ids.json').write_text('["dish_1"]', encoding='utf-8')
        for method in ('yolo_sam', 'vlm'):
            (self.results / method).mkdir(parents=True)
        self.context = self.run_export()['context']
        self.raw = '{"items":[{"name":"watermelon","grams":10}]}'
        table = {'watermelon': {'kcal':30, 'protein':1, 'fat':0, 'carb':6}}
        self.prediction = dict(to_result(self.raw, ['watermelon'], table), raw=self.raw,
                               context=self.context, experiment={'provider':'openai', 'model':'fixture',
                                                                'prompt':'fixture', 'image_id':'dish_1'})
        self.write('yolo_sam/dish_1.json', self.prediction)

    def write(self, name, value):
        path = self.results / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def run_export(self, repeats=3):
        return export(self.root, self.results, self.output, expected_repeats=repeats)

    def test_raw_response_must_agree_with_prediction(self):
        tampered = dict(self.prediction, raw='{"items":[]}')
        self.write('vlm/dish_1_r0.json', tampered)
        result = self.run_export(1)
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(result['coverage']['dish_1']['vlm']['valid_predictions'], 0)
        self.assertIn('invalid', result['coverage']['dish_1']['vlm']['states'])
        with zipfile.ZipFile(self.output) as archive:
            saved = json.loads(archive.read('results/vlm/dish_1_r0.json'))
            self.assertEqual(saved['raw'], '{"items":[]}')

    def test_alias_deduplicated_and_repeat_gaps_not_complete(self):
        for name in ('dish_1.json', 'dish_1_r0.json'):
            self.write(f'vlm/{name}', self.prediction)
        result = self.run_export(1)
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['coverage']['dish_1']['vlm']['valid_predictions'], 1)
        self.write('vlm/dish_1_r2.json', self.prediction)
        result = self.run_export(2)
        self.assertFalse(result['coverage_complete'])
        self.assertFalse(result['vlm_repetitions_complete'])
        self.assertFalse(result['coverage']['dish_1']['vlm']['repeat_sequence_valid'])

    def test_credentials_and_non_evidence_files_are_excluded(self):
        token = 'fixture-value-not-a-real-credential'
        self.write('vlm/dish_1_r0.json', dict(self.prediction, VLM_API_KEY=token))
        (self.results / 'vlm/.env').write_text(token)
        (self.results / 'vlm/dish_1.pt').write_text('fixture-weight')
        result = self.run_export()
        self.assertEqual(len(result['omitted']), 1)
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(name.endswith(('.env', '.pt')) for name in archive.namelist()))
            combined = b''.join(archive.read(name) for name in archive.namelist())
            self.assertNotIn(token.encode(), combined)

    def test_stale_predictions_and_failure_raw_remain_distinct(self):
        stale = copy.deepcopy(self.prediction)
        stale['context']['data_sha256'] = 'outdated'
        self.write('vlm/dish_1_r0.json', stale)
        self.write('vlm/failures/dish_1_r1_uuid.json',
                   {'status':'failed', 'raw':'malformed fixture response', 'error_type':'ValueError'})
        result = self.run_export()
        states = result['coverage']['dish_1']['vlm']['states']
        self.assertIn('stale_context', states)
        self.assertIn('failed', states)
        self.assertFalse(result['coverage_complete'])
        with zipfile.ZipFile(self.output) as archive:
            failure = json.loads(archive.read('results/vlm/failures/dish_1_r1_uuid.json'))
            self.assertEqual(failure['raw'], 'malformed fixture response')


if __name__ == '__main__':
    unittest.main()
