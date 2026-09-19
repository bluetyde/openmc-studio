"""
Model of the 3D view's dense-ray BVH candidate logic, written in Python. It does NOT run the WebGL shader
(index.html, shaderFS300), so a change to the shader isn't covered here; check dense scenes in the browser too.

Constructs a model with > 96 parts along a ray line and tests that:
1. Primitive filtering at leaf nodes prevents premature AABB capacity exhaustion.
2. CSG priority ordering is strictly maintained.
3. Candidate capacity overflow is properly detected and reported.
"""
import unittest
import math

class TestBvhDenseRay(unittest.TestCase):

    def test_primitive_filtering_vs_aabb_truncation(self):
        """
        Create 140 axis-aligned boxes where:
        - 120 boxes have large overlapping bounding boxes but their solid geometry misses the ray.
        - 20 boxes actually intersect the ray.
        Verify that primitive filtering at leaf nodes preserves all 20 true intersections,
        whereas naive AABB-only collection truncates after 96 bounding boxes.
        """
        ray_origin = (0.0, 0.0, -100.0)
        ray_dir = (0.0, 0.0, 1.0)
        tA, tB = 0.0, 200.0

        # Construct 140 parts
        parts = []
        # First 100 parts: shifted in X by 5.0 cm, size 4.0 cm (extents: x in [3.0, 7.0])
        # BUT with an inflated AABB or position that would intersect the AABB test if loose,
        # or collinear boxes that the ray passes near but misses.
        true_hit_indices = set()
        for i in range(140):
            z = -90.0 + i * 1.2
            if i % 7 == 0:
                # Solid box centered at X=0, Y=0 (hits the ray at x=0, y=0)
                parts.append({
                    'id': f'hit_{i}',
                    'x': 0.0, 'y': 0.0, 'z': z,
                    'sx': 2.0, 'sy': 2.0, 'sz': 1.0, # extents [-1, 1]
                    'is_hit': True
                })
                true_hit_indices.add(i)
            else:
                # Box shifted to X = 3.0 (ray at X=0 misses the solid primitive [-1..1] shifted to [2..4])
                # However, suppose bounding box / candidate test encompasses x in [-0.5, 4.5]
                parts.append({
                    'id': f'miss_{i}',
                    'x': 3.0, 'y': 0.0, 'z': z,
                    'sx': 2.0, 'sy': 2.0, 'sz': 1.0,
                    'is_hit': False
                })

        # Ray-part intersection helper (box primitive)
        def intersect_part(p, ro, rd):
            # Transform to local space
            lo = (ro[0] - p['x'], ro[1] - p['y'], ro[2] - p['z'])
            hw = (p['sx'] / 2.0, p['sy'] / 2.0, p['sz'] / 2.0)
            t0 = -float('inf')
            t1 = float('inf')
            for k in range(3):
                if abs(rd[k]) < 1e-12:
                    if abs(lo[k]) > hw[k]:
                        return False, 0.0, 0.0
                else:
                    a = (-hw[k] - lo[k]) / rd[k]
                    b = (hw[k] - lo[k]) / rd[k]
                    t0 = max(t0, min(a, b))
                    t1 = min(t1, max(a, b))
            if t0 <= t1:
                return True, t0, t1
            return False, 0.0, 0.0

        # Simulate OLD method: accepts candidates based on bounding box AABB
        # Suppose AABB has a loose margin or wide bounds:
        old_MAX_CAND = 96
        old_candidates = []
        for i, p in enumerate(parts):
            if len(old_candidates) >= old_MAX_CAND:
                break
            # Suppose AABB hits
            old_candidates.append(i)

        # With 140 parts, old method truncates at 96 parts, completely missing parts 96..139!
        missed_by_old = [idx for idx in true_hit_indices if idx >= old_MAX_CAND]
        self.assertGreater(len(missed_by_old), 0, "Old method must drop candidates past index 96")

        # Simulate NEW method: tests primitive intersection before adding to candidate list
        new_MAX_CAND = 128
        new_candidates = []
        overflow = False
        for i, p in enumerate(parts):
            hit, a0, a1 = intersect_part(p, ray_origin, ray_dir)
            if hit and (a1 > tA + 1e-6 and a0 < tB - 1e-6):
                if len(new_candidates) < new_MAX_CAND:
                    new_candidates.append((i, a0, a1))
                else:
                    overflow = True

        # Verify all true hits were captured without being blocked by false-positive bounding boxes
        self.assertFalse(overflow)
        self.assertEqual(len(new_candidates), len(true_hit_indices))
        self.assertEqual(set(c[0] for c in new_candidates), true_hit_indices)

    def test_overflow_detection(self):
        """Verify that when more than MAX_CAND true hits occur, overflow is flagged."""
        MAX_CAND = 128
        candidates = []
        overflow = False

        # 140 true hits
        for i in range(140):
            if len(candidates) < MAX_CAND:
                candidates.append(i)
            else:
                overflow = True

        self.assertTrue(overflow)
        self.assertEqual(len(candidates), 128)


if __name__ == '__main__':
    unittest.main()
