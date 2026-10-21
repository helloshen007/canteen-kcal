"""三种提示词写法,用于对比"提示词设计"的影响。"""
SCHEMA = '''只输出一个 JSON,不要任何额外文字或 Markdown,格式:
{"dishes":[{"name":"菜名","weight_g":数字,"kcal":数字,"protein_g":数字,"fat_g":数字,"carb_g":数字,"reason":"判断依据"}],
 "total":{"kcal":数字,"protein_g":数字,"fat_g":数字,"carb_g":数字},
 "advice":"针对用户目标的一两句建议"}'''
REF = "参考:中国食堂常见分量——一份米饭约150-200g,一份炒菜约100-150g,一块鸡腿约120g;食堂菜油偏多。"

def naive(goal): return f"这是一张食堂餐盘照片,用户目标是{goal}。请告诉我吃了多少热量。"
def structured(goal): return f"你是营养师。分析这张食堂餐盘照片,用户目标:{goal}。逐道菜估算重量(克)和营养。\n{SCHEMA}"
def structured_ref(goal): return structured(goal) + "\n" + REF + "\n先判断每道菜的名称和相对分量,再给出数字。"

def hybrid(goal, context_json):
    return (f"你是营养师。下面是检测模型对这张食堂餐盘照片的结果(位置、面积占比、估算重量),可能有错:\n{context_json}\n"
            f"请结合图片校正菜名,修正明显不合理的重量,并给出营养估算。用户目标:{goal}。\n{SCHEMA}\n{REF}")
PROMPTS = {"naive": naive, "structured": structured, "structured_ref": structured_ref}
