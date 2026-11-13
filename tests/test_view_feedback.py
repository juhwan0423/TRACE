import unittest
from haiclaw.harness import Harness
from haiclaw.core import Incident
from haiclaw.providers.harness_fixture import FixtureTools

class ViewFeedbackTests(unittest.TestCase):
    def make(self):
        h=Harness('episode',None,FixtureTools());h.incident=Incident('episode',0,180);h.incident.tick(10)
        h.view_observations['body']=dict(view_epoch=0,capture_time=9,clear_subject=False,same_view_attempts=2,person_visible='no')
        return h
    def test_alternating_cameras_does_not_reset_blind_view_budget(self):
        h=self.make();h._last_action=('observe','fixed');h._repeat=1
        catalog={(a['tool'],a['target']) for a in h.catalog()}
        self.assertNotIn(('observe','body'),catalog)
        self.assertIn(('observe','fixed'),catalog)
        self.assertIn(('inspect','east_inspection'),catalog)
        self.assertIn(('escalate',''),catalog)
    def test_actual_viewpoint_change_reenables_body(self):
        h=self.make();h.view_epoch+=1
        self.assertIn(('observe','body'),{(a['tool'],a['target']) for a in h.catalog()})
    def test_old_observation_allows_later_retry(self):
        h=self.make();h.incident.tick(60)
        self.assertIn(('observe','body'),{(a['tool'],a['target']) for a in h.catalog()})
    def test_clear_subject_is_not_treated_as_a_blind_view(self):
        h=self.make();h.view_observations['body']['clear_subject']=True
        self.assertIn(('observe','body'),{(a['tool'],a['target']) for a in h.catalog()})
    def test_sensor_ablation_never_advertises_disabled_camera(self):
        h=self.make();h.tools.cameras=('body',);h.view_epoch+=1
        self.assertEqual([a['target'] for a in h.catalog() if a['tool']=='observe'],['body'])
    def test_previous_viewpoint_outcome_is_available_without_forcing_a_move(self):
        h=self.make();h.memory=[dict(camera='body',viewpoint='east_inspection',observation={'person_visible':'uncertain'})]
        entry=next(a for a in h.catalog() if a['tool']=='inspect' and a['target']=='east_inspection')
        self.assertEqual(entry['previous_observations'],h.memory)
        self.assertIn(('escalate',''),{(a['tool'],a['target']) for a in h.catalog()})
