"""候选类别词表。YOLO-World 是开放词汇检测,用英文食材名当类别,不需要训练。
词表 = 评估子集(data/ground_truth.csv)里出现过的所有可见食材(封闭词表设定)。"""
import csv

# 配方里有、但图上看不见的调料/无效名称:既不当检测类别,评估时也不计入真值
INVISIBLE = {"olive oil", "salt", "pepper", "vinegar", "garlic", "deprecated", "water"}

def candidate_names(path="data/ground_truth.csv"):
    names = set()
    for r in csv.DictReader(open(path, encoding="utf-8")):
        for item in r["dishes"].split(";"):
            n = item.rsplit(":", 1)[0].strip()
            if n and n not in INVISIBLE:
                names.add(n)
    return sorted(names)