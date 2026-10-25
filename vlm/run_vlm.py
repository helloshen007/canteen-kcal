"""方案 B 批量推理。仅缓存明确成功且数据/模型/提示词一致的结果。"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from compare.evaluate import load_gt
from compare.provenance import evaluation_context, load_prediction, write_json
from detector.vocab import candidate_names
from vlm.client import call_vlm, parse_json, resolve_model_name, thinking_setting

OUT = Path('results/vlm')
PROMPT = '''你是食物营养分析助手。这是一张餐盘的俯拍照片。
请判断图中可见食物及每种食物的总重量（克）。只输出 JSON，不输出解释。
名称必须原样选自以下词表，不能猜测看不见的调料或油：
{vocab}
格式：{{"items":[{{"name":"strawberries","grams":57}}]}}
若确定没有任何可见食物，输出 {{"items":[]}}。'''


def to_result(text, vocab, table):
    data = parse_json(text)
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise ValueError('回复必须是包含 items 数组的 JSON 对象')
    canon = {name.lower(): name for name in vocab}
    weights = {}
    for item in data['items']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('每项必须包含名称和数值重量')
        name = canon.get(item['name'].strip().lower())
        grams = item.get('grams')
        if name is None:
            raise ValueError('食材名称不在封闭词表中')
        try:
            valid = not isinstance(grams, bool) and isinstance(grams, (int, float)) and math.isfinite(grams) and grams >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError('重量必须是非负有限数值')
        weights[name] = weights.get(name, 0) + grams
        if not math.isfinite(weights[name]):
            raise ValueError('累计重量溢出')
    dishes = []
    for name, grams in weights.items():
        if name not in table:
            raise ValueError('食材不在营养表中')
        nutrients = {}
        for target, source in (('kcal','kcal'),('protein_g','protein'),('fat_g','fat'),('carb_g','carb')):
            value = grams / 100 * float(table[name][source])
            if not math.isfinite(value) or value < 0:
                raise ValueError('营养换算结果无效')
            nutrients[target] = round(value, 1)
        dishes.append({'name': name, 'weight_g': round(grams), **nutrients})
    total = {key: round(sum(d[key] for d in dishes), 1) for key in ('kcal','protein_g','fat_g','carb_g')}
    return {'status': 'success', 'parse_ok': True, 'dishes': dishes, 'total': total, 'advice': []}


def redact(text):
    secret = os.getenv('VLM_API_KEY')
    return text.replace(secret, '[REDACTED]') if secret else text


def failure(out, iid, repeat, *, raw=None, error_type, reason, attempt=None, original=None):
    record = {'status':'failed', 'image_id':iid, 'repetition':repeat, 'attempt':attempt,
              'error_type':error_type, 'reason':reason, 'raw':redact(raw) if isinstance(raw,str) else raw}
    if original is not None:
        record['original_file'] = original.name
        record['original_content'] = redact(original.read_text(encoding='utf-8', errors='replace'))
    target = out / 'failures' / f'{iid}_r{repeat}_{uuid4().hex}.json'
    write_json(target, record)
    return target


def cache_valid(path, context, experiment, vocab, table):
    saved = load_prediction(path, context)
    if saved.get('parse_ok') is not True or saved.get('experiment') != experiment or not isinstance(saved.get('raw'),str):
        raise ValueError('缓存缺少有效回复或实验配置不一致')
    parsed = to_result(saved['raw'], vocab, table)
    if any(parsed[key] != saved[key] for key in ('dishes','total')):
        raise ValueError('缓存预测与原始回复不一致')
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reps', nargs='?', type=int, default=3)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--retry-delay', type=float, default=3)
    parser.add_argument('--results-root', type=Path, default=Path('results'))
    args = parser.parse_args(argv)
    if args.reps < 1 or args.attempts < 1 or (args.limit is not None and args.limit < 1) or args.retry_delay < 0:
        parser.error('次数和 limit 必须为正数，等待时间不能为负')
    gt, vocab = load_gt(), candidate_names()
    context = evaluation_context()
    with open('data/ingredient_nutrition.csv', encoding='utf-8') as stream:
        table = {r['name']:r for r in csv.DictReader(stream)}
    prompt = PROMPT.format(vocab=', '.join(vocab))
    out = args.results_root / 'vlm'
    ids = [iid for iid, g in gt.items() if g['split']=='test']
    if args.limit is not None:
        ids = ids[:args.limit]
    failed = 0
    for n, iid in enumerate(ids, 1):
        image = Path('data/images') / f'{iid}.jpg'
        if not image.is_file():
            raise SystemExit(f'缺少图片 {image}；先运行 python -m data.prepare')
        provider = os.getenv('VLM_PROVIDER', 'anthropic')
        endpoint = ((os.getenv('VLM_BASE_URL') or os.getenv('OPENAI_BASE_URL') or 'https://api.openai.com/v1')
                    if provider == 'openai' else (os.getenv('ANTHROPIC_BASE_URL') or 'https://api.anthropic.com'))
        experiment = {'provider':provider, 'model':resolve_model_name(os.getenv('VLM_MODEL',''), provider, endpoint),
                      'image_id':iid, 'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                      'prompt':prompt, 'disable_thinking':thinking_setting(),
                      'endpoint_sha256':hashlib.sha256(endpoint.encode()).hexdigest()}
        for repeat in range(args.reps):
            path = out / f'{iid}_r{repeat}.json'
            display = out / f'{iid}.json'
            if path.exists():
                try:
                    saved = cache_valid(path, context, experiment, vocab, table)
                except (ValueError, OSError):
                    failure(out,iid,repeat,error_type='InvalidCache',reason='旧版本/损坏/失败缓存已隔离，需重新请求',original=path)
                    path.unlink()
                    if repeat == 0 and display.exists():
                        failure(out,iid,repeat,error_type='InvalidDisplayCache',reason='对应主缓存已失效',original=display)
                        display.unlink()
                else:
                    if repeat == 0:
                        write_json(display,saved)
                    print(f'[{n}/{len(ids)}] {iid} r{repeat}: 有效缓存')
                    continue
            # 单独展示文件不能充当有效的重复实验缓存。
            if repeat == 0 and display.exists():
                failure(out,iid,repeat,error_type='UnverifiedDisplayCache',reason='缺少对应有效重复缓存',original=display)
                display.unlink()
            if not os.getenv('VLM_API_KEY') or not experiment['model']:
                failure(out,iid,repeat,error_type='MissingConfiguration',reason='需通过环境设置或 .env 配置 VLM_API_KEY 和 VLM_MODEL')
                raise SystemExit('缺少 VLM_API_KEY 或 VLM_MODEL，失败缓存已隔离；补齐配置后可重跑')
            start = time.monotonic()
            for attempt in range(1, args.attempts+1):
                raw = None
                try:
                    raw = call_vlm(str(image),prompt)
                    parsed = to_result(raw,vocab,table)
                    parsed.update(raw=redact(raw), context=context, experiment=experiment,
                                  seconds=round(time.monotonic()-start,2))
                    write_json(path,parsed)
                    if repeat == 0:
                        write_json(display,parsed)
                    print(f'[{n}/{len(ids)}] {iid} r{repeat}: 成功')
                    break
                except Exception as exc:
                    # 不记录 HTTP 异常正文，防止服务端回显密钥。
                    failure(out,iid,repeat,raw=raw,error_type=type(exc).__name__,reason='请求或输出校验失败',attempt=attempt)
                    print(f'{iid} r{repeat} attempt {attempt}: {type(exc).__name__}')
                    if attempt < args.attempts:
                        time.sleep(args.retry_delay)
            else:
                failed += 1
    if failed:
        raise SystemExit(f'{failed} 份预测失败；失败记录在 {out / "failures"}，再次运行会重试，不会把失败算成零热量')


if __name__ == '__main__':
    main()
