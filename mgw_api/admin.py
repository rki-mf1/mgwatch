# mgw_api/admin.py

from django.contrib import admin
from .models import Fasta, Signature, Settings, Result

# Register your models here.

admin.site.register(Fasta)
admin.site.register(Signature)
admin.site.register(Settings)
admin.site.register(Result)

#from .models import Choice, Question


#class ChoiceInline(admin.StackedInline):
#class ChoiceInline(admin.TabularInline):
#    model = Choice
#    extra = 3

#class QuestionAdmin(admin.ModelAdmin):
#    #fields = ["pub_date", "question_text"]
#    fieldsets = [
#        (None, {"fields": ["question_text"]}),
#        ("Date information", {"fields": ["pub_date"], 
#                              "classes": ["collapse"]}),
#    ]
#    inlines = [ChoiceInline]
#    list_display = ["question_text", "pub_date", "was_published_recently"]
#    list_filter = ["pub_date"]
#    search_fields = ["question_text"]


#admin.site.register(Question, QuestionAdmin)

