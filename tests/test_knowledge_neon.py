"""Embedding contract validation prevents corrupted vectors from reaching search."""
import pytest
from alphacouncil.knowledge.neon import DIMENSIONS,validate_embeddings


def record(index=0,vector=None):
    return {'index':index,'embedding':vector if vector is not None else [0.1]*DIMENSIONS}


def test_embeddings_restore_provider_batch_order():
    a,b=[0.1]*DIMENSIONS,[0.2]*DIMENSIONS
    assert validate_embeddings({'data':[record(1,b),record(0,a)]},2)==[a,b]


@pytest.mark.parametrize('rows',[
    [],[record(0),record(0)],[record(3)],
    [record(0,[0.1]*5)],[record(0,[float('nan')]*DIMENSIONS)],
    [record(0,[float('inf')]*DIMENSIONS)],[record(0,[True]*DIMENSIONS)],
    [record(0,[0.0]*DIMENSIONS)],
])
def test_invalid_or_misaligned_embeddings_are_rejected(rows):
    with pytest.raises(ValueError):
        validate_embeddings({'data':rows},2 if len(rows)==2 else 1)
