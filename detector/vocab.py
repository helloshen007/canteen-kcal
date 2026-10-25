"""The shared closed vocabulary is derived from corrected visible labels."""
import csv
from data.labels import INVISIBLE


def candidate_names(path="data/ground_truth.csv"):
    names = set()
    with open(path, encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            for item in row["visible_dishes"].split(";"):
                name = item.rsplit(":", 1)[0].strip()
                if name:
                    if name == "deprecated" or name.startswith("unresolved "):
                        raise ValueError("ground truth contains unaudited ingredient labels; rebuild/review it")
                    names.add(name)
    return sorted(names)
