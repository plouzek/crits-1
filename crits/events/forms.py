from django.conf import settings
from django import forms

from crits.core.forms import add_bucketlist_to_form, add_ticket_to_form
from crits.core.widgets import CalWidget
from crits.core.handlers import get_source_names, get_item_names
from crits.core.user_tools import get_user_organization
from crits.events.event import EventType

class EventForm(forms.Form):
    """
    Django form for creating a new Event.
    """

    error_css_class = 'error'
    required_css_class = 'required'
    title = forms.CharField(widget=forms.TextInput, required=True)
    event_type = forms.ChoiceField(required=True, widget=forms.Select)
    description = forms.CharField(widget=forms.Textarea(attrs={'cols': '30',
                                                               'rows': '3'}),
                                  required=False)
    occurrence_date = forms.DateTimeField(widget=CalWidget(format=settings.PY_DATETIME_FORMAT,
                                                           attrs={'class':'datetimeclass',
                                                                  'size':'25',
                                                                  'id':'id_occurrence_ip_date'}),
                                          input_formats=settings.PY_FORM_DATETIME_FORMATS)
    source = forms.ChoiceField(required=True, widget=forms.Select(attrs={'class': 'no_clear'}))
    reference = forms.CharField(widget=forms.TextInput, required=False)
    method = forms.CharField(widget=forms.TextInput, required=False)

    def __init__(self, username, *args, **kwargs):
        super(EventForm, self).__init__(*args, **kwargs)
        self.fields['source'].choices = [(c.name,
                                          c.name) for c in get_source_names(True,
                                                                               True,
                                                                               username)]
        self.fields['source'].initial = get_user_organization(username)
        self.fields['event_type'].choices = [(c.name,
                                              c.name) for c in get_item_names(EventType,
                                                                                 True)]

        add_bucketlist_to_form(self)
        add_ticket_to_form(self)
