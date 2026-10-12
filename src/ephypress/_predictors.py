"""Immutable integer predictor definitions shared with the compiled kernel.

Existing IDs must never be reassigned. Frames record the definition as well as
the ID, and readers reject a different registry rather than decode silently.
"""
import json
from pathlib import Path

MODELS=json.loads(Path(__file__).with_name('_predictors.json').read_text())
assert [model['id'] for model in MODELS]==list(range(32,32+len(MODELS)))
for model in MODELS:
    assert model['temporal_denominator']==16 and model['spatial_denominator']==32
    assert 0<=model['temporal']<=16 and 1<=len(model['spatial'])<=12
    assert all(isinstance(w,int) and -64<=w<=64 for w in model['spatial'])
REGISTRY={model['id']:model for model in MODELS}


def cpp_definitions():
    def values(items):return ','.join(str(x) for x in items)
    return ('constexpr int SPC_MODEL_COUNT='+str(len(MODELS))+';\n'
            'constexpr int SPC_TEMPORAL[]={'+values(m['temporal'] for m in MODELS)+'};\n'
            'constexpr int SPC_ORDER[]={'+values(len(m['spatial']) for m in MODELS)+'};\n'
            'constexpr int SPC_WEIGHTS[][12]={'+','.join('{'+values(m['spatial']+[0]*(12-len(m['spatial'])))+'}' for m in MODELS)+'};\n'
            '#define SPC_FOR_EACH_MODEL(F) '+' '.join(f'F({i})' for i in range(len(MODELS)))+'\n')
