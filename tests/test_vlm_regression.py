from contextlib import contextmanager, chdir
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vlm.run_vlm as batch
from vlm.client import normalize, resolve_model_name, thinking_setting

VOCAB = ['watermelon']
TABLE = {'watermelon': {'kcal':'30','protein':'0.6','fat':'0.1','carb':'7.6'}}
CONTEXT = {'data_sha256':'fixed-test-data','vocabulary':VOCAB}
VALID = '{"items":[{"name":"watermelon","grams":68}]}'


@contextmanager
def experiment():
    with tempfile.TemporaryDirectory() as folder, chdir(folder):
        Path('data/images').mkdir(parents=True)
        Path('data/images/dish_test.jpg').write_bytes(b'fixture image; API mocked')
        Path('data/ingredient_nutrition.csv').write_text('name,kcal,protein,fat,carb\nwatermelon,30,.6,.1,7.6\n')
        with patch.object(batch,'load_gt',return_value={'dish_test':{'split':'test'}}), \
             patch.object(batch,'candidate_names',return_value=VOCAB), \
             patch.object(batch,'evaluation_context',return_value=CONTEXT), \
             patch.dict(os.environ,{'VLM_API_KEY':'fixture-secret','VLM_MODEL':'fixture','VLM_PROVIDER':'openai'}):
            yield Path(folder)


def run_once(attempts=2):
    batch.main(['1','--attempts',str(attempts),'--retry-delay','0'])


class VLMRegressionTests(unittest.TestCase):
    def test_verified_deepseek_display_name_and_non_thinking_default(self):
        with patch.dict(os.environ, {'VLM_PROVIDER':'openai','VLM_BASE_URL':'https://api.deepseek.com'}):
            with patch.dict(os.environ):
                os.environ.pop('VLM_DISABLE_THINKING',None)
                self.assertEqual(resolve_model_name('DeepSeek V4.1 Flash'),'deepseek-flash')
                self.assertEqual(thinking_setting(),'1')
            with patch.dict(os.environ, {'VLM_DISABLE_THINKING':'0'}):
                self.assertEqual(thinking_setting(),'0')
        self.assertEqual(resolve_model_name('DeepSeek V4.1 Flash','openai','https://example.com'), 'DeepSeek V4.1 Flash')

    def test_bad_formats_cannot_become_zero_predictions(self):
        for text in (None,'','not JSON','{}','[]','{"items":null}','{"items":{}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                batch.to_result(text,VOCAB,TABLE)
        for data in (None, {"dishes":[{}]}, {"dishes":[{"name":"watermelon"}]}):
            with self.assertRaises(ValueError): normalize(data)

    def test_invalid_items_are_rejected(self):
        for item in (None,{}, {'name':'unknown','grams':1}, {'name':'watermelon','grams':True},
                     {'name':'watermelon','grams':-1}, {'name':'watermelon','grams':float('nan')},
                     {'name':'watermelon','grams':float('inf')}, {'name':'watermelon','grams':10**400},
                     {'name':'watermelon','grams':'bad'}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                batch.to_result(json.dumps({'items':[item]}),VOCAB,TABLE)

    def test_explicit_empty_array_is_a_valid_empty_prediction(self):
        result=batch.to_result('{"items":[]}',VOCAB,TABLE)
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['total']['kcal'],0)

    def test_valid_reply_uses_shared_nutrition(self):
        result=batch.to_result(VALID,VOCAB,TABLE)
        self.assertEqual(result['total']['kcal'],20.4)
        self.assertEqual(result['dishes'][0]['weight_g'],68)

    def test_bad_reply_is_saved_separately_then_retried(self):
        with experiment(), patch.object(batch,'call_vlm',side_effect=['{}',VALID]) as call:
            run_once()
            self.assertEqual(call.call_count,2)
            result=json.loads(Path('results/vlm/dish_test_r0.json').read_text())
            self.assertEqual(result['raw'],VALID)
            self.assertEqual(result['status'],'success')
            records=list(Path('results/vlm/failures').glob('*.json'))
            self.assertEqual(len(records),1)
            failed=json.loads(records[0].read_text())
            self.assertEqual(failed['raw'],'{}')
            self.assertEqual(failed['status'],'failed')
            self.assertNotIn('dishes',failed)

    def test_all_failed_leaves_no_prediction_and_next_run_retries(self):
        with experiment():
            with patch.object(batch,'call_vlm',return_value='garbage'), self.assertRaises(SystemExit):
                run_once(1)
            self.assertFalse(Path('results/vlm/dish_test_r0.json').exists())
            self.assertFalse(Path('results/vlm/dish_test.json').exists())
            with patch.object(batch,'call_vlm',return_value=VALID) as call:
                run_once(1)
                self.assertEqual(call.call_count,1)

    def test_old_zero_cache_is_quarantined_not_skipped(self):
        with experiment():
            out=Path('results/vlm');out.mkdir(parents=True)
            legacy={'dishes':[],'total':{'kcal':0},'parse_ok':False,'raw':'bad'}
            for name in ('dish_test_r0.json','dish_test.json'):
                (out/name).write_text(json.dumps(legacy))
            with patch.object(batch,'call_vlm',return_value=VALID) as call:
                run_once(1)
                self.assertEqual(call.call_count,1)
            self.assertEqual(json.loads((out/'dish_test.json').read_text())['total']['kcal'],20.4)
            self.assertGreaterEqual(len(list((out/'failures').glob('*.json'))),2)

    def test_success_cache_skips_call_and_changed_context_retries(self):
        with experiment():
            with patch.object(batch,'call_vlm',return_value=VALID) as call:
                run_once(1);run_once(1)
                self.assertEqual(call.call_count,1)
                changed={**CONTEXT,'data_sha256':'changed'}
                with patch.object(batch,'evaluation_context',return_value=changed):run_once(1)
                self.assertEqual(call.call_count,2)

    def test_endpoint_change_invalidates_success_cache(self):
        with experiment(), patch.object(batch,'call_vlm',return_value=VALID) as call:
            run_once(1)
            with patch.dict(os.environ,{'VLM_BASE_URL':'https://different.example/v1'}):
                run_once(1)
            self.assertEqual(call.call_count,2)

    def test_exception_body_does_not_leak_key(self):
        with experiment(), patch.object(batch,'call_vlm',side_effect=ValueError('fixture-secret')):
            with self.assertRaises(SystemExit):run_once(1)
            for record in Path('results/vlm/failures').glob('*.json'):
                self.assertNotIn('fixture-secret',record.read_text())


if __name__=='__main__':unittest.main()
