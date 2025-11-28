from django.contrib import admin
from .models import MessageTemplate

@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "is_active", "updated_at")
    search_fields = ("code", "title", "content")
    readonly_fields = ("code",) # 建议创建后 code 不许改，防止代码里找不到
    
    def get_readonly_fields(self, request, obj=None):
        if obj: # 编辑模式下 code 只读
            return self.readonly_fields
        return ()