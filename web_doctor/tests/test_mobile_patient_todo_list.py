from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users.models import DoctorProfile, PatientProfile


@pytest.mark.django_db
class TestMobilePatientTodoListView:
    def setup_method(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="doc_mobile_todo",
            password="password",
            user_type=2,
            phone="13900139111",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Todo")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.patient = PatientProfile.objects.create(
            name="患者A",
            phone="13800138001",
            doctor=self.doctor_profile,
        )
        self.url = reverse("web_doctor:mobile_patient_todo_list")

    def test_requires_login_returns_json(self, client):
        response = client.get(self.url)
        assert response.status_code == 401
        payload = response.json()
        assert payload["success"] is False

    def test_invalid_params_returns_json(self, client):
        client.force_login(self.user)
        response = client.get(self.url, {"page": "0"})
        assert response.status_code == 400
        payload = response.json()
        assert payload["success"] is False

    def test_empty_data_renders(self, client):
        client.force_login(self.user)
        response = client.get(self.url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "暂无待办事项" in content
        assert 'id="todo-detail-modal"' in content

    def test_pagination_renders_second_page(self, client):
        now = timezone.now()
        for idx in range(11):
            PatientAlert.objects.create(
                patient=self.patient,
                doctor=self.doctor_profile,
                event_type=AlertEventType.DATA,
                event_level=AlertLevel.MILD,
                event_title=f"体征异常{idx}",
                event_content=f"内容{idx}",
                event_time=now - timedelta(minutes=idx),
                status=AlertStatus.PENDING,
            )

        client.force_login(self.user)
        response = client.get(self.url, {"page": 2, "pagesize": 10, "patient_id": self.patient.id})
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "体征异常10" in content
        assert "体征异常0" not in content

    def test_htmx_request_returns_partial_fragment(self, client):
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体征异常X",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )

        client.force_login(self.user)
        response = client.get(
            self.url,
            {"page": 1, "pagesize": 10, "patient_id": self.patient.id},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "data-todo-detail-trigger" in content
        assert 'id="todo-detail-modal"' not in content
