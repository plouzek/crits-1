import json
import urllib

from django.shortcuts import render_to_response, render
from django.template import RequestContext
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth.decorators import user_passes_test
from django.core.urlresolvers import reverse

from crits.core import form_consts
from crits.core.user_tools import user_can_view_data, user_sources, user_is_admin
from crits.emails.email import Email
from crits.emails.forms import EmailAttachForm, EmailYAMLForm, EmailOutlookForm
from crits.emails.forms import EmailEMLForm, EmailUploadForm, EmailRawUploadForm
from crits.emails.handlers import handle_email_fields, handle_yaml
from crits.emails.handlers import handle_eml, generate_email_cybox, handle_msg
from crits.emails.handlers import update_email_header_value, handle_pasted_eml
from crits.emails.handlers import get_email_detail, generate_email_jtable
from crits.emails.handlers import generate_email_csv
from crits.emails.handlers import create_email_attachment, get_email_formatted
from crits.emails.handlers import create_indicator_from_header_field


@user_passes_test(user_can_view_data)
def emails_listing(request,option=None):
    """
    Generate Email Listing template.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param option: Whether or not we should generate a CSV (yes if option is "csv")
    :type option: str
    :returns: :class:`django.http.HttpResponse`
    """

    if option == "csv":
        return generate_email_csv(request)
    return generate_email_jtable(request, option)

@user_passes_test(user_can_view_data)
def email_search(request):
    """
    Generate email search results.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    query = {}
    query[request.GET.get('search_type',
                          '')]=request.GET.get('q',
                                               '').strip()
    return HttpResponseRedirect(reverse('crits.emails.views.emails_listing')
                                + "?%s" % urllib.urlencode(query))

@user_passes_test(user_is_admin)
def email_del(request, email_id):
    """
    Delete an email.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to delete.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    email = Email.objects(id=email_id).first()
    if email:
        email.delete(username=request.user.username)
        return HttpResponseRedirect(reverse('crits.emails.views.emails_listing'))
    else:
        return render_to_response('error.html',
                                  {'error': "Could not delete email."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def upload_attach(request, email_id):
    """
    Upload an attachment for an email.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to upload attachment for.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    analyst = request.user.username
    sources = user_sources(analyst)
    email = Email.objects(id=email_id, source__name__in=sources).first()
    if not email:
        error = "Could not find email."
        return render_to_response("error.html",
                                    {"error": error},
                                    RequestContext(request))
    if request.method == 'POST':
        form = EmailAttachForm(request.user.username,
                               request.POST,
                               request.FILES)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            reference = cleaned_data['source_reference']
            campaign = cleaned_data['campaign']
            confidence = cleaned_data['confidence']
            source = cleaned_data['source']
            bucket_list = cleaned_data.get(form_consts.Common.BUCKET_LIST_VARIABLE_NAME)
            ticket = cleaned_data.get(form_consts.Common.TICKET_VARIABLE_NAME)

            if request.FILES or 'filename' in request.POST and 'md5' in request.POST:
                result = create_email_attachment(email,
                                                 cleaned_data,
                                                 reference,
                                                 source,
                                                 analyst,
                                                 campaign=campaign,
                                                 confidence=confidence,
                                                 bucket_list=bucket_list,
                                                 ticket=ticket,
                                                 files=request.FILES.get('filedata',None),
                                                 filename=request.POST.get('filename', None),
                                                 md5=request.POST.get('md5', None))
                if not result['success']:
                    return render_to_response("error.html",
                                            {"error": result['message'] },
                                            RequestContext(request))
            return HttpResponseRedirect(reverse('crits.emails.views.email_detail',
                                                args=[email_id]))
        else:
            return render_to_response("error.html",
                                      {"error": '%s' % form.errors },
                                      RequestContext(request))
    else:
        return HttpResponseRedirect(reverse('crits.emails.views.email_detail',
                                            args=[email_id]))

@user_passes_test(user_can_view_data)
def email_fields_add(request):
    """
    Upload an email using fields. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    fields_form = EmailUploadForm(request.user, request.POST)
    json_reply = {
                   'form': fields_form.as_table(),
                   'success': False,
                   'message': ""
                 }

    if request.method != "POST":
        message = "Must submit via POST"
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': message},
                                      RequestContext(request))

    if not fields_form.is_valid():
        message = "Form is invalid."
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': message},
                                      RequestContext(request))

    obj = handle_email_fields(fields_form.cleaned_data,
                              request.user.username,
                              "Upload")
    if not obj['status']:
        if request.is_ajax():
            json_reply['message'] = obj['reason']
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': obj['reason']},
                                      RequestContext(request))

    if request.is_ajax():
        json_reply['success'] = True
        del json_reply['form']
        json_reply['message'] = 'Email uploaded successfully. <a href="%s">View email.</a>' % reverse('crits.emails.views.email_detail', args=[obj['object'].id])
        return HttpResponse(json.dumps(json_reply),
                            mimetype="application/json")
    else:
        return HttpResponseRedirect(reverse('crits.emails.views.email_detail',
                                            args=[obj['object'].id]))

@user_passes_test(user_can_view_data)
def email_yaml_add(request, email_id=None):
    """
    Upload an email using YAML. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of an existing email to update.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    yaml_form = EmailYAMLForm(request.user, request.POST)
    json_reply = {
                   'form': yaml_form.as_table(),
                   'success': False,
                   'message': ""
                 }

    if request.method != "POST":
        message = "Must submit via POST"
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': message},
                                      RequestContext(request))

    if not yaml_form.is_valid():
        message = "Form is invalid."
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': message},
                                      RequestContext(request))

    obj = handle_yaml(yaml_form.cleaned_data['yaml_data'],
                      yaml_form.cleaned_data['source'],
                      yaml_form.cleaned_data['source_reference'],
                      request.user.username,
                      "Upload",
                      email_id=email_id,
                      save_unsupported=yaml_form.cleaned_data['save_unsupported'],
                      campaign=yaml_form.cleaned_data['campaign'],
                      confidence=yaml_form.cleaned_data['campaign_confidence'])
    if not obj['status']:
        if request.is_ajax():
            json_reply['message'] = obj['reason']
            return HttpResponse(json.dumps(json_reply),
                                mimetype="application/json")
        else:
            return render_to_response('error.html',
                                      {'error': obj['reason']},
                                      RequestContext(request))

    if request.is_ajax():
        json_reply['success'] = True
        json_reply['message'] = 'Email uploaded successfully. <a href="%s">View email.</a>' % reverse('crits.emails.views.email_detail', args=[obj['object'].id])
        return HttpResponse(json.dumps(json_reply),
                            mimetype="application/json")
    else:
        return HttpResponseRedirect(reverse('crits.emails.views.email_detail',
                                            args=[obj['object'].id]))

@user_passes_test(user_can_view_data)
def email_raw_add(request):
    """
    Upload an email using Raw. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    fields_form = EmailRawUploadForm(request.user, request.POST)
    json_reply = {
                   'form': fields_form.as_table(),
                   'success': False,
                   'message': ""
                 }
    if request.method != "POST":
        message = "Must submit via POST"
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply), mimetype="application/json")
        else:
            return render_to_response('error.html', {'error': message}, RequestContext(request))

    if not fields_form.is_valid():
        message = "Form is invalid."
        if request.is_ajax():
            json_reply['message'] = message
            return HttpResponse(json.dumps(json_reply), mimetype="application/json")
        else:
            return render_to_response('error.html', {'error': message}, RequestContext(request))

    obj = handle_pasted_eml(fields_form.cleaned_data['raw_email'],
                    fields_form.cleaned_data['source'],
                    fields_form.cleaned_data['source_reference'],
                    request.user.username, "Upload",
                    campaign=fields_form.cleaned_data['campaign'],
                    confidence=fields_form.cleaned_data['campaign_confidence'])
    if not obj['status']:
        if request.is_ajax():
            json_reply['message'] = obj['reason']
            return HttpResponse(json.dumps(json_reply), mimetype="application/json")
        else:
            return render_to_response('error.html', {'error': obj['reason']}, RequestContext(request))

    if request.is_ajax():
        json_reply['success'] = True
        del json_reply['form']
        json_reply['message'] = 'Email uploaded successfully. <a href="%s">View email.</a>' % reverse('crits.emails.views.email_detail', args=[obj['object'].id])
        return HttpResponse(json.dumps(json_reply), mimetype="application/json")
    else:
        return HttpResponseRedirect(reverse('crits.emails.views.email_detail', args=[obj['object'].id]))

@user_passes_test(user_can_view_data)
def email_eml_add(request):
    """
    Upload an email using EML.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    eml_form = EmailEMLForm(request.user, request.POST, request.FILES)
    json_reply = {
                   'form': eml_form.as_table(),
                   'success': False,
                   'message': ""
                 }

    if request.method != "POST":
        json_reply['message'] = "Must submit via POST."
        return render_to_response('file_upload_response.html',
                                  {'response': json.dumps(json_reply)},
                                  RequestContext(request))

    if not eml_form.is_valid():
        json_reply['message'] = "Form is invalid."
        return render_to_response('file_upload_response.html',
                                  {'response': json.dumps(json_reply)},
                                  RequestContext(request))

    data = ''
    for chunk in request.FILES['filedata']:
        data += chunk

    obj = handle_eml(data, eml_form.cleaned_data['source'],
                     eml_form.cleaned_data['source_reference'],
                     request.user.username,
                     "Upload",
                     campaign=eml_form.cleaned_data['campaign'],
                     confidence=eml_form.cleaned_data['campaign_confidence'])
    if not obj['status']:
        json_reply['message'] = obj['reason']
        return render_to_response('file_upload_response.html',
                                  {'response': json.dumps(json_reply)},
                                  RequestContext(request))

    json_reply['success'] = True
    json_reply['message'] = 'Email uploaded successfully. <a href="%s">View email.</a>' % reverse('crits.emails.views.email_detail', args=[obj['object'].id])
    return render_to_response('file_upload_response.html',
                              {'response': json.dumps(json_reply)},
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def email_outlook_add(request):
    """
    Provides upload capability for Outlook .msg files (OLE2.0 format using
    Compound File Streams). This function will import the email into CRITs and
    upload any attachments as samples

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    outlook_form = EmailOutlookForm(request.user, request.POST, request.FILES)
    json_reply = {
        'form': outlook_form.as_table(),
        'success': False,
        'message': ""
        }

    if request.method != "POST":
        json_reply['message'] = "Must submit via POST."
        return render(request, 'file_upload_response.html', {'response': json.dumps(json_reply)})

    if not outlook_form.is_valid():
        json_reply['message'] = "Form is invalid."
        return render(request, 'file_upload_response.html', {'response': json.dumps(json_reply)})

    analyst = request.user.username
    method = "Outlook MSG File Import"
    source = outlook_form.cleaned_data['source']
    source_reference = outlook_form.cleaned_data['source_reference']
    password = outlook_form.cleaned_data['password']
    campaign = outlook_form.cleaned_data['campaign']
    campaign_confidence = outlook_form.cleaned_data['campaign_confidence']

    result = handle_msg(request.FILES['msg_file'],
                        source,
                        source_reference,
                        analyst,
                        method,
                        password,
                        campaign,
                        campaign_confidence)

    json_reply['success'] = result['status']
    if not result['status']:
        json_reply['message'] = result['reason']
    else:
        json_reply['message'] = 'Email uploaded successfully. <a href="%s">View email.</a>' % reverse('crits.emails.views.email_detail', args=[result['obj_id']])
        if 'message' in result:
            json_reply['message'] += "<br />Attachments:<br />%s" % result['message']
    return render(request, 'file_upload_response.html', {'response': json.dumps(json_reply)})

@user_passes_test(user_can_view_data)
def email_detail(request, email_id):
    """
    Generate the Email detail page.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to get details for.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    template = 'email_detail.html'
    analyst = request.user.username
    if request.method == "GET" and request.is_ajax():
        return get_email_formatted(email_id,
                                   analyst,
                                   request.GET.get("format", "json"))
    (new_template, args) = get_email_detail(email_id, analyst)
    if new_template:
        template = new_template
    return render_to_response(template,
                              args,
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def indicator_from_header_field(request, email_id):
    """
    Create an indicator from a header field. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to get the header from.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST" and request.is_ajax():
        if 'type' in request.POST:
            header_field = request.POST['type']
            analyst = request.user.username
            sources = user_sources(analyst)
            email = Email.objects(id=email_id,
                                  source__name__in=sources).first()
            if not email:
                result = {
                    'success':  False,
                    'message':  "Could not find email."
                }
            else:
                if header_field in ("from_address, sender, reply_to"):
                    ind_type = "Address - e-mail"
                elif header_field in ("originating_ip", "x_originating_ip"):
                    ind_type = "Address - ipv4-addr"
                else:
                    ind_type = "String"
                result = create_indicator_from_header_field(email,
                                                            header_field,
                                                            ind_type,
                                                            analyst,
                                                            request)
        else:
            result = {
                'success':  False,
                'message':  "Type is a required value."
            }
        return HttpResponse(json.dumps(result), mimetype="application/json")
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX POST"},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def get_email_cybox(request, email_id):
    """
    Get a CybOX representation of an email. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to get.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST" and request.is_ajax():
        cybox = generate_email_cybox(email_id)
        return HttpResponse(json.dumps(cybox.to_xml()),
                            mimetype="application/json")
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX POST"},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def update_header_value(request, email_id):
    """
    Update the header value of an email. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param email_id: The ObjectId of the email to update a header for.
    :type email_id: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST" and request.is_ajax():
        type_ = request.POST.get('type', None)
        value = request.POST.get('value', None)
        analyst = request.user.username
        result = update_email_header_value(email_id,
                                           type_,
                                           value,
                                           analyst)
        return HttpResponse(json.dumps(result),
                            mimetype="application/json")
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX POST"},
                                  RequestContext(request))
