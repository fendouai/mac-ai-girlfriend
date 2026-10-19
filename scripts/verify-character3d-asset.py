"""Validate the exported binary, skin weights and nonzero facial morphs."""
import hashlib
import json
from pathlib import Path
import struct

import numpy as np

root = Path(__file__).resolve().parents[1]
path = root / 'web/assets/models/sweet-realistic.vrm'
data = path.read_bytes()
magic, version, size = struct.unpack_from('<III', data)
assert magic == 0x46546C67 and version == 2 and size == len(data)
length, kind = struct.unpack_from('<II', data, 12)
assert kind == 0x4E4F534A
doc = json.loads(data[20:20 + length])
binary_length, kind = struct.unpack_from('<II', data, 20 + length)
assert kind == 0x004E4942
binary = memoryview(data)[28 + length:28 + length + binary_length]
widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
dtypes = {5126: '<f4', 5125: '<u4', 5123: '<u2', 5121: 'u1'}


def accessor(index):
    item = doc['accessors'][index]
    dtype = np.dtype(dtypes[item['componentType']])
    width = widths[item['type']]
    if 'bufferView' in item:
        view = doc['bufferViews'][item['bufferView']]
        result = np.ndarray((item['count'], width), dtype=dtype, buffer=binary,
                            offset=view.get('byteOffset', 0) + item.get('byteOffset', 0),
                            strides=(view.get('byteStride', width * dtype.itemsize), dtype.itemsize))
    else:
        result = np.zeros((item['count'], width), dtype=dtype)
    if 'sparse' in item:
        sparse = item['sparse']
        indices = sparse['indices']
        index_view = doc['bufferViews'][indices['bufferView']]
        ids = np.frombuffer(binary, dtype=dtypes[indices['componentType']], count=sparse['count'],
                            offset=index_view.get('byteOffset', 0) + indices.get('byteOffset', 0))
        values = sparse['values']
        value_view = doc['bufferViews'][values['bufferView']]
        entries = np.frombuffer(binary, dtype=dtype, count=sparse['count'] * width,
                                offset=value_view.get('byteOffset', 0) + values.get('byteOffset', 0)).reshape(-1, width)
        result = result.copy()
        result[ids] = entries
    return result


for index, item in enumerate(doc['accessors']):
    if item['componentType'] == 5126:
        assert np.isfinite(accessor(index)).all(), f'Nonfinite float accessor {index}'
vrm = doc['extensions']['VRMC_vrm']
assert len(vrm['humanoid']['humanBones']) == 52
extents = {}
for mesh in doc['meshes']:
    names = mesh.get('extras', {}).get('targetNames', [])
    for primitive in mesh['primitives']:
        weights = primitive['attributes'].get('WEIGHTS_0')
        if weights is not None:
            values = accessor(weights)
            assert values.min() >= 0 and values.max() <= 1.00001
            assert np.max(np.abs(values.sum(axis=1) - 1)) < .001
        for name, target in zip(names, primitive.get('targets', [])):
            if 'POSITION' in target:
                extent = float(np.linalg.norm(accessor(target['POSITION']), axis=1).max())
                extents[name] = max(extents.get(name, 0), extent)
assert extents['aa'] > .002 and extents['blink'] > .001 and extents['happy'] > .0003, extents
manifest = json.loads(path.with_suffix('.source.json').read_text())
assert manifest['sha256'] == hashlib.sha256(data).hexdigest()
print(json.dumps({'passed': True, 'bytes': len(data), 'bones': 52, 'morph_maximum_displacement': extents}, indent=2))
