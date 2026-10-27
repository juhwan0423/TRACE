"""Load the pure corridor function without importing the Isaac runtime."""
import ast
import math
from pathlib import Path
import unittest

tree=ast.parse((Path(__file__).resolve().parents[1]/'scripts/real2sim_navigation.py').read_text())
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='corridor_indices')
namespace={'math':math}
exec(compile(ast.Module(body=[function],type_ignores=[]),'<corridor>','exec'),namespace)
route=namespace['corridor_indices']

class CorridorTests(unittest.TestCase):
    def test_closed_patrol_can_use_existing_return_segment(self):
        points=[(0,0),(10,0),(10,10),(0,1),(0,0)]
        self.assertEqual(route(points,0,3),[0,3])
        self.assertEqual(route(points,3,0),[3,0])
        self.assertEqual(route(points,4,3),[0,3])

    def test_open_corridor_never_creates_closing_shortcut(self):
        points=[(0,0),(10,0),(10,10),(0,1)]
        self.assertEqual(route(points,0,3),[0,1,2,3])
        self.assertEqual(route(points,3,0),[3,2,1,0])

    def test_same_point_has_no_extra_lap(self):
        self.assertEqual(route([(0,0),(1,0),(0,0)],0,0),[0])
