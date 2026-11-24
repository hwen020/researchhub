from decimal import Decimal, localcontext
from math import isfinite
from types import SimpleNamespace
from typing import Dict, List

from pydantic import BaseModel, ConfigDict, Field


class SummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    observations: list = Field(min_length=2, max_length=1024)

    def values(self):
        if any(type(value) is not int or abs(value) > 10**12 for value in self.observations):
            raise ValueError("Observations must be bounded integers")
        return self.observations


def summarize(parameters):
    values = SummaryInput.model_validate(parameters).values()
    count = len(values)
    total = sum(values)
    sum_squares = sum(value * value for value in values)
    with localcontext() as context:
        context.prec = 40
        return {
            "count": count, "min": min(values), "max": max(values),
            "mean": str(Decimal(total) / count),
            "sample_variance": str(Decimal(count * sum_squares - total * total) / (count * (count - 1))),
        }


class AgingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ages: List[float] = Field(min_length=4, max_length=128)
    expression: Dict[str, List[float]] = Field(min_length=1, max_length=32)

    def values(self):
        if any(not isfinite(age) or not 0 <= age <= 125 for age in self.ages):
            raise ValueError("Ages must be finite and between 0 and 125")
        if len(set(self.ages)) < 3:
            raise ValueError("At least three distinct ages are required")
        for feature, values in self.expression.items():
            if not feature.isascii() or not feature.isalnum() or len(feature) > 32:
                raise ValueError("Feature identifiers must be short and alphanumeric")
            if len(values) != len(self.ages) or any(not isfinite(value) or abs(value) > 100 for value in values):
                raise ValueError("Expression values must be finite, bounded and aligned with the ages")
        return self


def aging_associations(parameters):
    import pandas as pd

    from .aging_statistics import age_association

    data = AgingInput.model_validate(parameters).values()
    metadata = pd.DataFrame({"age": data.ages})
    expression = pd.DataFrame.from_dict(data.expression, orient="index")
    results = age_association(SimpleNamespace(metadata=metadata, expression=expression))
    return {"associations": results.to_dict(orient="records")}


PLUGINS = {"summary@1": summarize, "age-association@1": aging_associations}
INPUTS = {"summary@1": SummaryInput, "age-association@1": AgingInput}


def validate_parameters(plugin, parameters):
    model = INPUTS[plugin].model_validate(parameters)
    model.values()
    return model.model_dump()

