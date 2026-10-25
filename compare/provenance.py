"""共同数据版本与成功预测契约，阻止旧词表/错误输出污染评估。"""
import hashlib
import json
import math
from pathlib import Path
import tempfile


def evaluation_context():
    from detector.vocab import candidate_names
    digest = hashlib.sha256()
    for name in ('data/ground_truth.csv', 'data/ingredient_nutrition.csv'):
        digest.update(name.encode())
        digest.update(Path(name).read_bytes())
    vocabulary = candidate_names()
    digest.update(json.dumps(vocabulary, ensure_ascii=False).encode())
    return {'data_sha256': digest.hexdigest(), 'vocabulary': vocabulary}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_prediction(path, context=None):
    path = Path(path)
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(result, dict) or result.get('status') != 'success':
            raise ValueError('不是明确成功的预测，旧文件不能自动视为成功')
        if result.get('parse_ok') is False or result.get('parse_error'):
            raise ValueError('模型回复解析失败')
        if context is not None and result.get('context') != context:
            raise ValueError('真值/词表/营养表版本不一致')
        if not isinstance(result.get('dishes'), list):
            raise ValueError('缺少 dishes 数组')
        seen = set()
        for dish in result['dishes']:
            name = dish['name']
            if not isinstance(name, str) or not name or name in seen:
                raise ValueError('食材名缺失或重复')
            if context is not None and name not in context['vocabulary']:
                raise ValueError('食材不在当前词表')
            seen.add(name)
            for key in ('weight_g', 'kcal'):
                value = dish[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('重量/热量必须是非负有限数值')
        total = result['total']['kcal']
        if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0:
            raise ValueError('总热量无效')
        if abs(total - sum(d['kcal'] for d in result['dishes'])) > .11:
            raise ValueError('总热量与逐食材不一致')
        return result
    except (TypeError, KeyError, AttributeError, ValueError, OverflowError) as exc:
        raise ValueError(f'无效预测 {path}: {exc}') from exc
