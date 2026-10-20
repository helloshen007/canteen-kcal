"""营养表读取、重量估算、营养计算、膳食建议规则。纯逻辑,不依赖任何模型,可单独测试。"""
import csv, math
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Dish:
    name: str; kcal: float; protein: float; fat: float; carb: float  # 均为每100g
    height_cm: float; density: float; oil_factor: float

def load_table(path="data/dish_nutrition.csv") -> dict:
    table = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            table[r["name"]] = Dish(r["name"], *(float(r[k]) for k in
                ("kcal", "protein", "fat", "carb", "height_cm", "density", "oil_factor")))
    return table

def estimate_weight_g(mask_px, plate_px, dish: Dish, plate_diameter_cm=24.0):
    """像素面积 → 真实面积(用餐盘直径做尺度) → 体积(×堆积高度) → 重量(×密度)。"""
    plate_area_cm2 = math.pi * (plate_diameter_cm / 2) ** 2
    area_cm2 = mask_px / plate_px * plate_area_cm2
    return area_cm2 * dish.height_cm * dish.density

def nutrition_for(dish: Dish, weight_g):
    """食堂菜油量大:脂肪乘 oil_factor,多出的脂肪按 9 kcal/g 补进热量。"""
    k = weight_g / 100
    fat100 = dish.fat * dish.oil_factor
    kcal100 = dish.kcal + (fat100 - dish.fat) * 9
    return {"weight_g": round(weight_g), "kcal": round(kcal100 * k),
            "protein_g": round(dish.protein * k, 1), "fat_g": round(fat100 * k, 1),
            "carb_g": round(dish.carb * k, 1)}

def summarize(dishes):
    keys = ("kcal", "protein_g", "fat_g", "carb_g")
    return {k: round(sum(d.get(k, 0) for d in dishes), 1) for k in keys}

# 每餐参考范围(经验值,请对照《中国居民膳食指南》自行调整并在文档里说明出处)
GOALS = {"减脂": dict(kcal=(450, 650), protein_min=25, fat_ratio_max=0.30),
         "维持": dict(kcal=(600, 800), protein_min=20, fat_ratio_max=0.35),
         "增肌": dict(kcal=(700, 950), protein_min=35, fat_ratio_max=0.35)}

def advise(total, goal="减脂"):
    g, tips = GOALS[goal], []
    if total["kcal"] > g["kcal"][1]: tips.append(f"热量偏高(>{g['kcal'][1]} kcal),可减少主食或油炸/红烧类。")
    if total["kcal"] < g["kcal"][0]: tips.append(f"热量偏低(<{g['kcal'][0]} kcal),可适当加主食或蛋白质。")
    if total["protein_g"] < g["protein_min"]: tips.append("蛋白质不足,建议加一份蛋类、豆制品或瘦肉。")
    if total["kcal"] > 0 and total["fat_g"] * 9 / total["kcal"] > g["fat_ratio_max"]:
        tips.append("脂肪供能占比偏高,下一餐选清蒸/清炒类。")
    return tips or ["这一餐搭配比较均衡。"]
DISCLAIMER = "仅供参考,不构成医疗或营养诊疗建议。"
