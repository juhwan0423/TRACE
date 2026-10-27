import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('run_summary',Path(__file__).resolve().parents[1]/'scripts/summarize_real2sim_harness.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class SummaryTests(unittest.TestCase):
    def test_different_conditions_are_not_pooled(self):
        rows=[dict(conditions=k,wall_seconds=t,completed=True,state='escalated_unknown',source_verified=True)
              for k,t in [('all',10),('body',30),('all',20)]]
        groups={g['conditions']:g for g in module.aggregate(rows)}
        self.assertEqual(groups['all']['runs'],2)
        self.assertEqual(groups['all']['mean_wall_seconds'],15)
        self.assertEqual(groups['all']['unresolved'],2)
        self.assertEqual(groups['body']['runs'],1)

    def test_missing_source_verification_remains_visible(self):
        rows=[dict(conditions='a',wall_seconds=1,completed=False,state='escalated_unknown',source_verified=False)]
        group=module.aggregate(rows)[0]
        self.assertFalse(group['all_sources_verified'])
        self.assertEqual(group['completed'],0)
