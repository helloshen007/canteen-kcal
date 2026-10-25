"""兼容旧下载命令，保留已提交 ID 清单，不重新选样或覆盖划分。"""
import argparse
import json
from data.prepare import ROOT, main

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('count', nargs='?', type=int)
    args = parser.parse_args()
    count = len(json.loads((ROOT / 'data/dish_ids.json').read_text()))
    if args.count is not None and args.count != count:
        parser.error(f'固定实验只支持已有 {count} 张清单，请勿在复现时重新选样')
    main([])
