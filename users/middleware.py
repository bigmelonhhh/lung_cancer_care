from django.conf import settings
from django.utils.functional import SimpleLazyObject
from users.models import PatientProfile, PatientRelation
from users import choices
from users.choices import UserType

def get_actual_patient(request):
    """
    核心逻辑：计算当前请求对应的患者档案
    """
    
    user = request.user
    #优先保证登陆状态
    if not user.is_authenticated:
        return None
    
    #其次保证患者/家属身份
    if user.user_type != UserType.PATIENT:
        return None

    # 1. 如果当前登录用户本身绑定了患者档案（本人操作）
    # 基于 PatientProfile.user 是 OneToOneField
    if hasattr(user, 'patient_profile'):
        return user.patient_profile

    # 2. 如果是家属（没有绑定自己的档案，或者正在代理操作）
    # 优先从 Session 中获取当前选中的 patient_id（支持一个家属管理多个患者）
    session_patient_id = request.session.get('active_patient_id')
    

    if session_patient_id:
        # 校验家属是否有权管理该患者 (查询 PatientRelation)
        relation = PatientRelation.objects.filter(
            user=user, 
            is_active=True,
            patient_id=session_patient_id
        ).first()
        if relation:
            return relation.patient
    
    # 3. 如果 Session 没指定，默认取最近绑定的一个患者
    relation = PatientRelation.objects.filter(user=user, is_active=True).order_by('-created_at').first()
    if relation:
        # 自动帮用户种下 Session，方便后续使用
        request.session['active_patient_id'] = relation.patient_id
        return relation.patient

    return None

class PatientContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 本地调试辅助：在 DEBUG 模式下，如果配置了 TEST_PATIENT_ID，
        # 且当前为匿名用户访问患者端路径 (/p/ 开头)，则自动挂载指定患者对应的用户。
        test_patient_id = getattr(settings, "TEST_PATIENT_ID", None)
        if (
            settings.DEBUG
            and test_patient_id
            and request.path.startswith("/p/")
            and getattr(request, "user", None) is not None
            and not request.user.is_authenticated
        ):
            patient = (
                PatientProfile.objects.select_related("user")
                .filter(pk=test_patient_id)
                .first()
            )
            if patient and patient.user:
                user = patient.user
                # 为兼容部分依赖 backend 的逻辑，补充 backend 属性
                if not hasattr(user, "backend"):
                    user.backend = "django.contrib.auth.backends.ModelBackend"
                request.user = user
                # 保持与家属/多患者逻辑一致，种下 active_patient_id
                request.session["active_patient_id"] = patient.id

        # 使用 SimpleLazyObject 懒加载，避免不必要的数据库查询
        # 只有在代码里真正访问 request.patient 时才会去查库
        request.patient = SimpleLazyObject(lambda: get_actual_patient(request))

        response = self.get_response(request)
        return response
