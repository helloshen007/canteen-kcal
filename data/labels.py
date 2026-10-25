"""Canonical labels audited against ingredient IDs, never deprecated-name aliases."""

ANNOTATION_VERSION = "nutrition5k-id-correction-v1"
INVISIBLE = {"olive oil", "salt", "pepper", "vinegar", "garlic", "water"}

# HF metadata reuses "deprecated" for unrelated ingredient IDs. Only 0458 was
# manually verified as watermelon in the six selected images (see audit doc).
ID_NAME_OVERRIDES = {"ingr_0000000458": "watermelon"}


def ingredient_name(ingredient):
    ingredient_id = str(ingredient.get("id", "")).strip()
    name = str(ingredient.get("name", "")).replace(":", " ").replace(";", " ").strip()
    if ingredient_id in ID_NAME_OVERRIDES:
        return ID_NAME_OVERRIDES[ingredient_id]
    if name == "deprecated" or not name:
        if not ingredient_id:
            raise ValueError("deprecated ingredient has no ID; manual review required")
        return f"unresolved {ingredient_id}"
    return name
