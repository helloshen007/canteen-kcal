"""Regression checks for the ID-specific watermelon annotation correction."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from data.build_gt import build_ground_truth
from data.labels import ingredient_name
from detector.vocab import candidate_names


class AnnotationTests(unittest.TestCase):
    def test_deprecated_ids_are_not_a_global_name_alias(self):
        self.assertEqual(ingredient_name({'id': 'ingr_0000000458', 'name': 'deprecated'}), 'watermelon')
        self.assertEqual(ingredient_name({'id': 'ingr_0000000453', 'name': 'deprecated'}),
                         'unresolved ingr_0000000453')
        self.assertNotEqual(ingredient_name({'id': 'ingr_0000000453', 'name': 'deprecated'}), 'watermelon')

    def test_six_audited_test_images_have_nonzero_food_truth(self):
        expected = {
            'dish_1558027001': (68.0, 20.4, 'single'),
            'dish_1558027243': (163.0, 263.4, 'few'),
            'dish_1558028142': (73.0, 21.9, 'single'),
            'dish_1558028194': (172.0, 228.0, 'few'),
            'dish_1558028606': (65.0, 19.5, 'single'),
            'dish_1558028772': (192.0, 64.0, 'few'),
        }
        with open('data/ground_truth.csv', encoding='utf-8') as stream:
            truth = {row['image_id']: row for row in csv.DictReader(stream)}
        for iid, (mass, kcal, difficulty) in expected.items():
            with self.subTest(iid=iid):
                self.assertEqual(truth[iid]['split'], 'test')
                self.assertEqual(float(truth[iid]['visible_mass_g']), mass)
                self.assertEqual(float(truth[iid]['visible_kcal']), kcal)
                self.assertEqual(truth[iid]['difficulty'], difficulty)
                self.assertIn('watermelon:', truth[iid]['visible_dishes'])

    def test_fixed_split_and_shared_24_class_vocabulary(self):
        ids = json.loads(Path('data/dish_ids.json').read_text())
        with open('data/ground_truth.csv', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r['image_id'] for r in rows], ids)
        self.assertEqual([r['split'] for r in rows], ['calib'] * 40 + ['test'] * 20)
        self.assertTrue(all(r['difficulty'] != 'none' for r in rows[40:]))
        self.assertEqual(sum(r['difficulty'] == 'single' for r in rows[40:]), 15)
        vocabulary = candidate_names()
        self.assertEqual(len(vocabulary), 24)
        self.assertIn('watermelon', vocabulary)
        self.assertNotIn('deprecated', vocabulary)

    def test_generator_keeps_id_file_and_separates_unresolved_nutrition(self):
        # Small explicit fixtures exercise rebuilding without a network download.
        def row(iid, ingredient):
            return {'id': iid, 'ingredients': [ingredient], 'total_calories': ingredient['calories'],
                    'total_mass': ingredient['grams'], 'total_protein': ingredient['protein'],
                    'total_fat': ingredient['fat'], 'total_carb': ingredient['carb']}
        watermelon = {'id': 'ingr_0000000458', 'name': 'deprecated', 'grams': 68.0,
                      'calories': 20.4, 'protein': 0.408, 'fat': 0.068, 'carb': 5.168}
        other = {'id': 'ingr_0000000453', 'name': 'deprecated', 'grams': 143.0,
                 'calories': 74.36, 'protein': 20.02, 'fat': 0.286, 'carb': 0.429}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            metadata = folder / 'metadata.jsonl'
            metadata.write_text('\n'.join(json.dumps(r) for r in (
                row('dish_1', watermelon), row('dish_2', watermelon), row('dish_3', other))))
            ids = folder / 'dish_ids.json'
            ids.write_text('["dish_1", "dish_2"]')
            before_ids = ids.read_bytes()
            out = folder / 'generated'
            build_ground_truth(metadata, ids, out)
            first = {p.name: p.read_bytes() for p in out.iterdir()}
            build_ground_truth(metadata, ids, out)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, first)
            self.assertEqual(ids.read_bytes(), before_ids)
            with (out / 'ingredient_nutrition.csv').open() as stream:
                nutrition = {r['name']: r for r in csv.DictReader(stream)}
            self.assertEqual(float(nutrition['watermelon']['kcal']), 30)
            self.assertEqual(float(nutrition['watermelon']['protein']), 0.6)
            self.assertEqual(float(nutrition['unresolved ingr_0000000453']['protein']), 14)
            ids.write_text('["dish_1", "dish_3"]')
            with self.assertRaisesRegex(ValueError, 'manual label review'):
                build_ground_truth(metadata, ids, out)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, first)


if __name__ == '__main__':
    unittest.main()
