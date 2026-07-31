from django.test import SimpleTestCase

from users.models import PatientProfile


class GeneralMonitoringBaselineModelTests(SimpleTestCase):
    def test_patient_profile_exposes_three_general_monitoring_baselines(self):
        field_names = {field.name for field in PatientProfile._meta.get_fields()}

        self.assertIn("baseline_blood_glucose", field_names)
        self.assertIn("baseline_blood_ketone", field_names)
        self.assertIn("baseline_uric_acid", field_names)
