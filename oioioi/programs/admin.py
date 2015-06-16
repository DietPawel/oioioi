from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.conf.urls import patterns, url
from django.core.exceptions import PermissionDenied
from django.utils.translation import ugettext_lazy as _
from django.shortcuts import redirect
from django.core.urlresolvers import reverse
from django.contrib.admin.util import unquote
from django.utils.html import conditional_escape
from django.utils.encoding import force_unicode
from django.http import Http404

from oioioi.base.utils import make_html_link
from oioioi.contests.models import ProblemInstance
from oioioi.contests.admin import ProblemInstanceAdmin, SubmissionAdmin
from oioioi.problems.admin import ProblemPackageAdmin, MainProblemInstanceAdmin
from oioioi.programs.models import Test, ModelSolution, TestReport, \
        GroupReport, ModelProgramSubmission, OutputChecker, \
        LibraryProblemData, ReportActionsConfig
from collections import defaultdict


class TestInline(admin.TabularInline):
    model = Test
    max_num = 0
    extra = 0
    template = 'programs/admin/tests_inline.html'
    can_delete = False
    fields = ('name', 'time_limit', 'memory_limit', 'max_score', 'kind',
              'input_file_link', 'output_file_link', 'is_active')
    readonly_fields = ('name', 'kind', 'group', 'input_file_link',
            'output_file_link')
    ordering = ('kind', 'order', 'name')

    class Media(object):
        css = {
            'all': ('programs/admin.css',),
        }

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def input_file_link(self, instance):
        if instance.id is not None:
            href = reverse('oioioi.programs.views.download_input_file_view',
                    kwargs={'test_id': str(instance.id)})
            return make_html_link(href,
                                  instance.input_file.name.split('/')[-1])
        return None
    input_file_link.short_description = _("Input file")

    def output_file_link(self, instance):
        if instance.id is not None:
            href = reverse('oioioi.programs.views.download_output_file_view',
                    kwargs={'test_id': instance.id})
            return make_html_link(href,
                                  instance.output_file.name.split('/')[-1])
        return None
    output_file_link.short_description = _("Output/hint file")


class ReportActionsConfigInline(admin.StackedInline):
    model = ReportActionsConfig
    extra = 0
    inline_classes = ('collapse open',)
    fields = ['can_user_generate_outs']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


class OutputCheckerInline(admin.TabularInline):
    model = OutputChecker
    extra = 0
    fields = ['checker_link']
    readonly_fields = ['checker_link']
    can_delete = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def checker_link(self, instance):
        if not instance.exe_file:
            return _("No checker for this task.")

        if instance.id is not None:
            href = reverse('oioioi.programs.views.download_checker_exe_view',
                kwargs={'checker_id': str(instance.id)})
            return make_html_link(href, instance.exe_file.name.split('/')[-1])
        return None
    checker_link.short_description = _("Checker exe")


class LibraryProblemDataInline(admin.TabularInline):
    model = LibraryProblemData
    extra = 0
    fields = ['libname']
    readonly_fields = ['libname']
    can_delete = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


class LibraryProblemDataAdminMixin(object):
    def __init__(self, *args, **kwargs):
        super(LibraryProblemDataAdminMixin, self).__init__(*args, **kwargs)
        self.inlines = self.inlines + [LibraryProblemDataInline]


class ProgrammingProblemAdminMixin(object):
    def __init__(self, *args, **kwargs):
        super(ProgrammingProblemAdminMixin, self).__init__(*args, **kwargs)
        self.inlines = self.inlines + [ReportActionsConfigInline,
                                       OutputCheckerInline,
                                       LibraryProblemDataInline]


class ProgrammingProblemInstanceAdminMixin(object):
    def __init__(self, *args, **kwargs):
        super(ProgrammingProblemInstanceAdminMixin, self). \
                __init__(*args, **kwargs)
        self.inlines = self.inlines + [TestInline]

ProblemInstanceAdmin.mix_in(ProgrammingProblemInstanceAdminMixin)


class ProgrammingMainProblemInstanceAdminMixin(object):
    def __init__(self, *args, **kwargs):
        super(ProgrammingMainProblemInstanceAdminMixin, self). \
                __init__(*args, **kwargs)
        self.inlines = self.inlines + [TestInline]

MainProblemInstanceAdmin.mix_in(ProgrammingMainProblemInstanceAdminMixin)


class ProblemPackageAdminMixin(object):
    def inline_actions(self, package_instance, contest):
        actions = super(ProblemPackageAdminMixin, self) \
                .inline_actions(package_instance, contest)
        if package_instance.status == 'OK':
            try:
                problem_instance = package_instance.problem \
                    .main_problem_instance
                if not problem_instance:
                    problem_instance = ProblemInstance.objects.get(
                        problem=package_instance.problem, contest=contest)
                if (problem_instance.contest and ModelSolution.objects.filter(
                        problem=problem_instance.problem)):
                    models_view = reverse('model_solutions',
                                          args=(problem_instance.id,))
                    actions.append((models_view, _("Model solutions")))
            except ProblemInstance.DoesNotExist:
                pass
        return actions

ProblemPackageAdmin.mix_in(ProblemPackageAdminMixin)


class ModelSubmissionAdminMixin(object):
    def user_full_name(self, instance):
        if not instance.user:
            instance = instance.programsubmission
            if instance:
                instance = instance.modelprogramsubmission
                if instance:
                    return '(%s)' % (conditional_escape(force_unicode(
                        instance.model_solution.name)),)
        return super(ModelSubmissionAdminMixin, self).user_full_name(instance)

    user_full_name.short_description = \
            SubmissionAdmin.user_full_name.short_description
    user_full_name.admin_order_field = \
            SubmissionAdmin.user_full_name.admin_order_field

    def get_list_select_related(self):
        return super(ModelSubmissionAdminMixin, self) \
                .get_list_select_related() \
                + ['programsubmission', 'modelprogramsubmission']

SubmissionAdmin.mix_in(ModelSubmissionAdminMixin)


class ProgramSubmissionAdminMixin(object):
    def __init__(self, *args, **kwargs):
        super(ProgramSubmissionAdminMixin, self).__init__(*args, **kwargs)
        self.actions += ['submission_diff_action']

    def submission_diff_action(self, request, queryset):
        if len(queryset) != 2:
            messages.error(request,
                    _("You shall select exactly two submissions to diff"))
            return None

        id_older, id_newer = [sub.id for sub in queryset.order_by('date')]

        return redirect('source_diff', contest_id=request.contest.id,
                        submission1_id=id_older, submission2_id=id_newer)
    submission_diff_action.short_description = _("Diff submissions")

SubmissionAdmin.mix_in(ProgramSubmissionAdminMixin)
