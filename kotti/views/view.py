from pyramid.exceptions import NotFound
from pyramid.view import render_view_to_response

from kotti.resources import Document
from kotti.views.util import template_api

def view_content_default(context, request):
    """This view is always registered as the default view for any Content.

    Its job is to delegate to a view of which the name may be defined
    per instance.  If a instance level view is not defined for
    'context' (in 'context.defaultview'), we will fall back to a view
    with the name 'view'.
    """
    view_name = context.default_view or u'view'
    response = render_view_to_response(context, request, name=view_name)
    if response is None: # pragma: no coverage
        raise NotFound()
    return response

def view_node(context, request):
    return {'api': template_api(context, request)}

def includeme(config):
    config.add_view(
        view_node,
        context=Document,
        name='view',
        permission='view',
        renderer='../templates/view/document.pt',
        )
