from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils import translation
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_POST
from oioioi.base.menu import menu_registry
from oioioi.base.permissions import not_anonymous, enforce_condition
from oioioi.contests.controllers import submission_template_context
from oioioi.contests.forms import SubmissionForm
from oioioi.contests.models import ProblemInstance, Submission, \
        SubmissionReport, ContestAttachment
from oioioi.contests.utils import visible_contests, can_enter_contest, \
        is_contest_admin, has_any_submittable_problem, \
        visible_problem_instances, contest_exists, get_submission_or_404
from oioioi.filetracker.utils import stream_file
from oioioi.problems.models import ProblemStatement, ProblemAttachment
from operator import itemgetter
import sys


def select_contest_view(request):
    contests = visible_contests(request)
    return TemplateResponse(request, 'contests/select_contest.html',
            {'contests': contests})

@enforce_condition(contest_exists & can_enter_contest)
def default_contest_view(request, contest_id):
    url = request.contest.controller.default_view(request)
    return HttpResponseRedirect(url)


@menu_registry.register_decorator(_("Problems"), lambda request:
        reverse('problems_list', kwargs={'contest_id': request.contest.id}),
    order=100)
@enforce_condition(contest_exists & can_enter_contest)
def problems_list_view(request, contest_id):
    problem_instances = visible_problem_instances(request)
    show_rounds = len(frozenset(pi.round_id for pi in problem_instances)) > 1
    return TemplateResponse(request, 'contests/problems_list.html',
                {'problem_instances': problem_instances,
                 'show_rounds': show_rounds})

@enforce_condition(contest_exists & can_enter_contest)
def problem_statement_view(request, contest_id, problem_instance):
    controller = request.contest.controller
    pi = get_object_or_404(ProblemInstance, round__contest=request.contest,
            short_name=problem_instance)

    if not controller.can_see_problem(request, pi):
        raise PermissionDenied

    statements = ProblemStatement.objects.filter(problem=pi.problem)
    if not statements:
        return TemplateResponse(request, 'contests/no_problem_statement.html',
                    {'problem_instance': pi})

    lang_prefs = [translation.get_language()] + ['', None] + \
            [l[0] for l in settings.LANGUAGES]
    ext_prefs = ['.pdf', '.ps', '.html', '.txt']

    def sort_key(statement):
        try:
            lang_pref = lang_prefs.index(statement.language)
        except ValueError:
            lang_pref = sys.maxint
        try:
            ext_pref = (ext_prefs.index(statement.extension), '')
        except ValueError:
            ext_pref = (sys.maxint, statement.extension)
        return lang_pref, ext_pref

    statement = sorted(statements, key=sort_key)[0]
    return stream_file(statement.content)

@menu_registry.register_decorator(_("Submit"), lambda request:
        reverse('submit', kwargs={'contest_id': request.contest.id}),
    order=300)
@enforce_condition(contest_exists & can_enter_contest)
@enforce_condition(has_any_submittable_problem,
                   template='contests/nothing_to_submit.html')
def submit_view(request, contest_id):
    if request.method == 'POST':
        form = SubmissionForm(request, request.POST, request.FILES)
        if form.is_valid():
            request.contest.controller.create_submission(request,
                    form.cleaned_data['problem_instance'], form.cleaned_data)
            return redirect('my_submissions', contest_id=contest_id)
    else:
        form = SubmissionForm(request)
    return TemplateResponse(request, 'contests/submit.html', {'form': form})

@menu_registry.register_decorator(_("My submissions"), lambda request:
        reverse('my_submissions', kwargs={'contest_id': request.contest.id}),
    order=400)
@enforce_condition(not_anonymous & contest_exists & can_enter_contest)
def my_submissions_view(request, contest_id):
    queryset = Submission.objects \
            .filter(problem_instance__contest=request.contest) \
            .order_by('-date') \
            .select_related()
    controller = request.contest.controller
    queryset = controller.filter_visible_submissions(request, queryset)
    show_scores = bool(queryset.filter(score__isnull=False))
    return TemplateResponse(request, 'contests/my_submissions.html',
                {'submissions': [submission_template_context(request, s)
                    for s in queryset], 'show_scores': show_scores})

@enforce_condition(contest_exists & can_enter_contest)
def submission_view(request, contest_id, submission_id):
    submission = get_submission_or_404(request, contest_id, submission_id)
    controller = request.contest.controller
    header = controller.render_submission(request, submission)
    footer = controller.render_submission_footer(request, submission)
    reports = []
    queryset = SubmissionReport.objects.filter(submission=submission). \
        prefetch_related('scorereport_set')
    for report in controller.filter_visible_reports(request, submission,
            queryset.filter(status='ACTIVE')):
        reports.append(controller.render_report(request, report))

    all_reports = is_contest_admin(request) and \
        controller.filter_visible_reports(request, submission, queryset) or \
        []

    return TemplateResponse(request, 'contests/submission.html',
                {'submission': submission, 'header': header, 'footer': footer,
                    'reports': reports, 'all_reports': all_reports})

@enforce_condition(contest_exists & is_contest_admin)
def report_view(request, contest_id, submission_id, report_id):
    submission = get_submission_or_404(request, contest_id, submission_id)
    controller = request.contest.controller
    queryset = SubmissionReport.objects.filter(submission=submission)
    report = get_object_or_404(queryset, id=report_id)
    return HttpResponse(controller.render_report(request, report))

@enforce_condition(contest_exists & is_contest_admin)
@require_POST
def rejudge_submission_view(request, contest_id, submission_id):
    submission = get_submission_or_404(request, contest_id, submission_id)
    controller = request.contest.controller
    controller.judge(submission, request.GET.dict())
    messages.info(request, _("Rejudge request received."))
    return redirect('submission', contest_id=contest_id,
            submission_id=submission_id)

@enforce_condition(contest_exists & is_contest_admin)
@require_POST
def change_submission_kind_view(request, contest_id, submission_id, kind):
    submission = get_submission_or_404(request, contest_id, submission_id)
    controller = request.contest.controller
    if kind in controller.valid_kinds_for_submission(submission):
        controller.change_submission_kind(submission, kind)
        messages.success(request, _("Submission kind has been changed."))
    else:
        messages.error(request,
            _("%(kind)s is not valid kind for submission %(submission_id)d.")
            % {'kind': kind,
               'submission_id': submission.id
            })
    return redirect('submission', contest_id=contest_id,
                    submission_id=submission_id)

@menu_registry.register_decorator(_("Files"), lambda request:
        reverse('contest_files', kwargs={'contest_id': request.contest.id}),
    order=200)
@enforce_condition(not_anonymous & contest_exists & can_enter_contest)
def contest_files_view(request, contest_id):
    contest_files = ContestAttachment.objects.filter(contest=request.contest)
    problem_instances = visible_problem_instances(request)
    problem_ids = [pi.problem_id for pi in problem_instances]
    problem_files = \
            ProblemAttachment.objects.filter(problem_id__in=problem_ids)
    rows = [{
        'name': cf.filename,
        'description': cf.description,
        'link': reverse('contest_attachment', kwargs={'contest_id': contest_id,
            'attachment_id': cf.id}),
        } for cf in contest_files]
    rows += [{
        'name': pf.filename,
        'description': u'%s: %s' % (pf.problem, pf.description),
        'link': reverse('problem_attachment', kwargs={'contest_id': contest_id,
            'attachment_id': pf.id}),
        } for pf in problem_files]
    rows.sort(key=itemgetter('name'))
    return TemplateResponse(request, 'contests/files.html', {'files': rows})

@enforce_condition(contest_exists & can_enter_contest)
def contest_attachment_view(request, contest_id, attachment_id):
    attachment = get_object_or_404(ContestAttachment, contest_id=contest_id,
        id=attachment_id)
    return stream_file(attachment.content)

@enforce_condition(contest_exists & can_enter_contest)
def problem_attachment_view(request, contest_id, attachment_id):
    attachment = get_object_or_404(ProblemAttachment, id=attachment_id)
    problem_instances = visible_problem_instances(request)
    problem_ids = [pi.problem_id for pi in problem_instances]
    if attachment.problem_id not in problem_ids:
        raise PermissionDenied
    return stream_file(attachment.content)
