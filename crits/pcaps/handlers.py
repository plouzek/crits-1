import crits.service_env
import datetime
import hashlib
import json

from bson.objectid import ObjectId
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext
from mongoengine.base import ValidationError

from crits.core.class_mapper import class_from_id, class_from_value
from crits.core.crits_mongoengine import create_embedded_source, json_handler
from crits.core.crits_mongoengine import EmbeddedSource
from crits.core.handlers import build_jtable, jtable_ajax_list, jtable_ajax_delete
from crits.core.handlers import csv_export
from crits.core.user_tools import is_admin, user_sources, is_user_favorite
from crits.core.user_tools import is_user_subscribed
from crits.notifications.handlers import remove_user_from_notification
from crits.pcaps.pcap import PCAP
from crits.services.handlers import run_triage


def generate_pcap_csv(request):
    """
    Generate a CSV file of the PCAP information.

    :param request: The request for this CSV.
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    response = csv_export(request, PCAP)
    return response

def get_pcap_details(md5, analyst):
    """
    Generate the data to render the PCAP details template.

    :param md5: The MD5 of the PCAP to get details for.
    :type md5: str
    :param analyst: The user requesting this information.
    :type analyst: str
    :returns: template (str), arguments (dict)
    """

    template = None
    sources = user_sources(analyst)
    pcap = PCAP.objects(md5=md5, source__name__in=sources).first()
    if not pcap:
        template = "error.html"
        args = {'error': 'PCAP not yet available or you do not have access to view it.'}
    else:

        pcap.sanitize("%s" % analyst)

        # remove pending notifications for user
        remove_user_from_notification("%s" % analyst, pcap.id, 'PCAP')

        # subscription
        subscription = {
                'type': 'PCAP',
                'id': pcap.id,
                'subscribed': is_user_subscribed("%s" % analyst,
                                                 'PCAP', pcap.id),
        }

        #objects
        objects = pcap.sort_objects()

        #relationships
        relationships = pcap.sort_relationships("%s" % analyst, meta=True)

        # relationship
        relationship = {
                'type': 'PCAP',
                'value': pcap.id
        }

        #comments
        comments = {'comments': pcap.get_comments(),
                    'url_key': md5}

        # favorites
        favorite = is_user_favorite("%s" % analyst, 'PCAP', pcap.id)

        # services
        manager = crits.service_env.manager
        # Assume all PCAPs have the data available
        service_list = manager.get_supported_services('PCAP', True)

        args = {'service_list': service_list,
                'objects': objects,
                'relationships': relationships,
                'comments': comments,
                'favorite': favorite,
                'relationship': relationship,
                "subscription": subscription,
                "pcap": pcap}

    return template, args

def generate_pcap_jtable(request, option):
    """
    Generate the jtable data for rendering in the list template.

    :param request: The request for this jtable.
    :type request: :class:`django.http.HttpRequest`
    :param option: Action to take.
    :type option: str of either 'jtlist', 'jtdelete', or 'inline'.
    :returns: :class:`django.http.HttpResponse`
    """

    obj_type = PCAP
    type_ = "pcap"
    mapper = obj_type._meta['jtable_opts']
    if option == "jtlist":
        # Sets display url
        details_url = mapper['details_url']
        details_url_key = mapper['details_url_key']
        fields = mapper['fields']
        response = jtable_ajax_list(obj_type,
                                    details_url,
                                    details_url_key,
                                    request,
                                    includes=fields)
        return HttpResponse(json.dumps(response,
                                       default=json_handler),
                            content_type="application/json")
    if option == "jtdelete":
        response = {"Result": "ERROR"}
        if jtable_ajax_delete(obj_type,request):
            response = {"Result": "OK"}
        return HttpResponse(json.dumps(response,
                                       default=json_handler),
                            content_type="application/json")
    jtopts = {
        'title': "PCAPs",
        'default_sort': mapper['default_sort'],
        'listurl': reverse('crits.%ss.views.%ss_listing' % (type_,
                                                            type_),
                           args=('jtlist',)),
        'deleteurl': reverse('crits.%ss.views.%ss_listing' % (type_,
                                                              type_),
                             args=('jtdelete',)),
        'searchurl': reverse(mapper['searchurl']),
        'fields': mapper['jtopts_fields'],
        'hidden_fields': mapper['hidden_fields'],
        'linked_fields': mapper['linked_fields'],
        'details_link': mapper['details_link'],
        'no_sort': mapper['no_sort']
    }
    jtable = build_jtable(jtopts,request)
    jtable['toolbar'] = [
        {
            'tooltip': "'All PCAPs'",
            'text': "'All'",
            'click': "function () {$('#pcap_listing').jtable('load', {'refresh': 'yes'});}",
            'cssClass': "'jtable-toolbar-center'",
        },
        {
            'tooltip': "'New PCAPs'",
            'text': "'New'",
            'click': "function () {$('#pcap_listing').jtable('load', {'refresh': 'yes', 'status': 'New'});}",
            'cssClass': "'jtable-toolbar-center'",
        },
        {
            'tooltip': "'In Progress PCAPs'",
            'text': "'In Progress'",
            'click': "function () {$('#pcap_listing').jtable('load', {'refresh': 'yes', 'status': 'In Progress'});}",
            'cssClass': "'jtable-toolbar-center'",
        },
        {
            'tooltip': "'Analyzed PCAPs'",
            'text': "'Analyzed'",
            'click': "function () {$('#pcap_listing').jtable('load', {'refresh': 'yes', 'status': 'Analyzed'});}",
            'cssClass': "'jtable-toolbar-center'",
        },
        {
            'tooltip': "'Deprecated PCAPs'",
            'text': "'Deprecated'",
            'click': "function () {$('#pcap_listing').jtable('load', {'refresh': 'yes', 'status': 'Deprecated'});}",
            'cssClass': "'jtable-toolbar-center'",
        },
        {
            'tooltip': "'Add PCAP'",
            'text': "'Add PCAP'",
            'click': "function () {$('#new-pcap').click()}",
        },
    ]
    if option == "inline":
        return render_to_response("jtable.html",
                                  {'jtable': jtable,
                                   'jtid': '%s_listing' % type_,
                                   'button' : '%ss_tab' % type_},
                                  RequestContext(request))
    else:
        return render_to_response("%s_listing.html" % type_,
                                  {'jtable': jtable,
                                   'jtid': '%s_listing' % type_},
                                  RequestContext(request))

def handle_pcap_file(filename, data, source_name, user=None,
                     description=None, parent_id=None, parent_md5=None,
                     parent_type=None, method=None, relationship=None,
                     bucket_list=None, ticket=None):
    """
    Add a PCAP.

    :param filename: The filename of the PCAP.
    :type filename: str
    :param data: The filedata of the PCAP.
    :type data: str
    :param source_name: The source which provided this PCAP.
    :type source_name: str,
                       :class:`crits.core.crits_mongoengine.EmbeddedSource`,
                       list of :class:`crits.core.crits_mongoengine.EmbeddedSource`
    :param user: The user adding the PCAP.
    :type user: str
    :param description: Description of the PCAP.
    :type description: str
    :param parent_id: ObjectId of the top-level object where this PCAP came from.
    :type parent_id: str
    :param parent_md5: MD5 of the top-level object where this PCAP came from.
    :type parent_md5: str
    :param parent_type: The CRITs type of the parent.
    :type parent_type: str
    :param method: The method of acquiring this PCAP.
    :type method: str
    :param relationship: The relationship between the parent and the PCAP.
    :type relationship: str
    :param bucket_list: Bucket(s) to add to this PCAP.
    :type bucket_list: str(comma separated) or list.
    :param ticket: Ticket(s) to add to this PCAP.
    :type ticket: str(comma separated) or list.
    :returns: dict with keys:
              'success' (boolean),
              'message' (str),
              'md5' (str) if successful.
    """

    if not data:
        status = {
            'success':   False,
            'message':  'No data object passed in'
        }
        return status
    if len(data) <= 0:
        status = {
            'success':   False,
            'message':  'Data length <= 0'
        }
        return status

    # generate md5 and timestamp
    md5 = hashlib.md5(data).hexdigest()
    timestamp = datetime.datetime.now()

    # generate PCAP
    is_pcap_new = False
    pcap = PCAP.objects(md5=md5).first()
    if not pcap:
        pcap = PCAP()
        pcap.filename = filename
        pcap.created = timestamp
        pcap.length = len(data)
        pcap.description = description
        pcap.md5 = md5
        is_pcap_new = True

    # generate source information and add to pcap
    if isinstance(source_name, basestring) and len(source_name) > 0:
        s = create_embedded_source(source_name,
                                   method=method,
                                   reference='',
                                   analyst=user)
        pcap.add_source(s)
    elif isinstance(source_name, EmbeddedSource):
        pcap.add_source(source_name)
    elif isinstance(source_name, list) and len(source_name) > 0:
        for s in source_name:
            if isinstance(s, EmbeddedSource):
                pcap.add_source(s)

    # add file to GridFS
    if not isinstance(pcap.filedata.grid_id, ObjectId):
        pcap.add_file_data(data)

    if bucket_list:
        pcap.add_bucket_list(bucket_list, user)

    if ticket:
        pcap.add_ticket(ticket, user)

    # save pcap
    pcap.save(username=user)

    # update parent relationship if a parent is supplied
    if parent_id or parent_md5:
        if not relationship:
            relationship = "Related_To"
        if  parent_id:
            parent_obj = class_from_id(parent_type, parent_id)
        else:
            parent_obj = class_from_value(parent_type, parent_md5)
        if parent_obj and pcap:
            pcap.add_relationship(rel_item=parent_obj,
                                  rel_type=relationship,
                                  analyst=user,
                                  get_rels=False)
            parent_obj.save(username=user)
            pcap.save(username=user)

    # run pcap triage
    if is_pcap_new and data:
        pcap.reload()
        run_triage(data, pcap, user)

    status = {
        'success':      True,
        'message':      'Uploaded pcap',
        'md5':          md5,
    }

    return status

def update_pcap_description(md5, description, analyst):
    """
    Update a PCAP description.

    :param md5: The MD5 of the PCAP to update.
    :type md5: str
    :param description: The new description.
    :type description: str
    :param analyst: The user updating the description.
    :type analyst: str
    :returns: None, ValidationError
    """

    pcap = PCAP.objects(md5=md5).first()
    pcap.description = description
    try:
        pcap.save(username=analyst)
        return None
    except ValidationError, e:
        return e

def delete_pcap(pcap_md5, username=None):
    """
    Delete a PCAP.

    :param pcap_md5: The MD5 of the PCAP to delete.
    :type pcap_md5: str
    :param username: The user deleting the certificate.
    :type username: str
    :returns: True, False
    """

    if is_admin(username):
        pcap = PCAP.objects(md5=pcap_md5).first()
        if pcap:
            pcap.delete(username=username)
            return True
        else:
            return False
    else:
        return False
