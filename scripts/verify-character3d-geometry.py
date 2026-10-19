"""Check shared seam topology independently of Blender and model weights."""
import numpy as np
from character3d_geometry import edge_loops, stitch_loops, inside_polygon

for axis in [np.array([0, 0, 1]), np.array([0, -1, 0])]:
    theta = np.arange(23) * 2 * np.pi / 23
    phi = np.arange(37) * 2 * np.pi / 37 + .03
    a = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(23)])
    b = np.column_stack([.8 * np.cos(phi), .8 * np.sin(phi), np.zeros(37)])
    if axis[1]:
        a = a[:, [0, 2, 1]]
        b = b[:, [0, 2, 1]]
    vertices = np.vstack([a, b])
    triangles = stitch_loops(list(range(23)), list(range(23, 60)), vertices, axis, angular=True)
    edges = {}
    for triangle in triangles:
        for i in range(3):
            edge = tuple(sorted([int(triangle[i]), int(triangle[(i + 1) % 3])]))
            edges[edge] = edges.get(edge, 0) + 1
    assert max(edges.values()) == 2
    assert len(edge_loops([edge for edge, count in edges.items() if count == 1])) == 2
    normals = np.cross(vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
                       vertices[triangles[:, 2]] - vertices[triangles[:, 0]]) @ axis
    assert np.all(normals > 0) or np.all(normals < 0), 'Seam contains reversed triangles'
assert inside_polygon(np.array([[0, 0], [2, 2]]), np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]])).tolist() == [True, False]
print('PASS: seam winding, integer axes, boundary topology and polygon selection')
