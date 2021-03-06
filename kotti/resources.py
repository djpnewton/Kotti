from UserDict import DictMixin

import transaction
from sqlalchemy.orm import backref
from sqlalchemy.orm import mapper
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import relation
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import Table
from sqlalchemy import Column
from sqlalchemy import UniqueConstraint
from sqlalchemy import ForeignKey
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from pyramid.traversal import resource_path

from kotti import get_version
from kotti import get_settings
from kotti import DBSession
from kotti import metadata
from kotti.util import ViewLink
from kotti.util import JsonType
from kotti.util import MutationDict
from kotti.security import PersistentACL
from kotti.security import get_principals
from kotti.security import view_permitted
from kotti.security import SITE_ACL

class Container(object, DictMixin):
    """Containers form the API of a Node that's used for subitem
    access and in traversal.
    """
    def __getitem__(self, key):
        key = unicode(key)
        session = DBSession()
        query = session.query(Node).filter(
            Node.name==key).filter(Node.parent==self)
        try:
            return query.one()
        except NoResultFound:
            raise KeyError(key)

    def __setitem__(self, key, node):
        node.name = unicode(key)
        self.children.append(node)

    def __delitem__(self, key):
        node = self[unicode(key)]
        self.children.remove(node)
        DBSession().delete(node)

    def keys(self):
        return [child.name for child in self.children]

class Node(Container, PersistentACL):
    id = None
    def __init__(self, name=None, parent=None, title=u"", annotations=None):
        if annotations is None:
            annotations = {}
        self.name = name
        self.parent = parent
        self.title = title
        self.annotations = annotations

    # Provide location-awareness through __name__ and __parent__
    @property
    def __name__(self):
        return self.name

    @property
    def __parent__(self):
        return self.parent

    def __repr__(self): # pragma: no cover
        return '<%s %s at %s>' % (
            self.__class__.__name__, self.id, resource_path(self))

    def __eq__(self, other):
        return isinstance(other, Node) and self.id == other.id

    def copy(self, **kwargs):
        copy = self.__class__()
        for prop in object_mapper(self).iterate_properties:
            if prop.key not in ('id', 'parent', 'children'):
                setattr(copy, prop.key, getattr(self, prop.key))
        for key, value in kwargs.items():
            setattr(copy, key, value)
        children = list(self.children)
        for child in children:
            copy.children.append(child.copy())
        return copy

class TypeInfo(object):
    addable_to = ()

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def copy(self, **kwargs):
        d = self.__dict__.copy()
        d.update(kwargs)
        return TypeInfo(**d)

    def addable(self, context, request):
        """Return True if the type described in 'self' may be added to
        'context'.
        """
        if view_permitted(context, request, self.add_view):
            return context.type_info.name in self.addable_to
        else:
            return False

class Content(Node):
    type_info = TypeInfo(
        name=u'Content',
        add_view=None,
        addable_to=[],
        edit_links=[
            ViewLink('edit'),
            ViewLink('add'),
            ViewLink('move'),
            ViewLink('share'),
            ],
        )

    def __init__(self, name=None, parent=None, title=u"", annotations=None,
                 default_view=None, description=u"", language=None,
                 owner=None, creation_date=None, modification_date=None,
                 in_navigation=True):
        super(Content, self).__init__(name, parent, title, annotations)
        self.default_view = default_view
        self.description = description
        self.language = language
        self.owner = owner
        self.in_navigation = in_navigation
        # These are set by events if not defined at this point:
        self.creation_date = creation_date
        self.modification_date = modification_date

class Document(Content):
    type_info = Content.type_info.copy(
        name=u'Document',
        add_view=u'add_document',
        addable_to=[u'Document'],
        )

    def __init__(self, body=u"", mime_type='text/html', **kwargs):
        super(Document, self).__init__(**kwargs)
        self.body = body
        self.mime_type = mime_type

nodes = Table('nodes', metadata,
    Column('id', Integer, primary_key=True),
    Column('type', String(30), nullable=False),
    Column('parent_id', ForeignKey('nodes.id')),
    Column('position', Integer),
    Column('_acl', JsonType()),
    Column('__roles__', JsonType()),

    Column('name', Unicode(50), nullable=False),
    Column('title', Unicode(100)),
    Column('annotations', MutationDict.as_mutable(JsonType)),

    UniqueConstraint('parent_id', 'name'),
)

contents = Table('contents', metadata,
    Column('id', Integer, ForeignKey('nodes.id'), primary_key=True),
    Column('default_view', String(50)),
    Column('description', UnicodeText()),
    Column('language', Unicode(10)),
    Column('owner', Unicode(100)),
    Column('creation_date', DateTime()),
    Column('modification_date', DateTime()),
    Column('in_navigation', Boolean()),
)

documents = Table('documents', metadata,
    Column('id', Integer, ForeignKey('contents.id'), primary_key=True),
    Column('body', UnicodeText()),
    Column('mime_type', String(30)),
)

mapper(
    Node,
    nodes,
    polymorphic_on=nodes.c.type,
    polymorphic_identity='node',
    with_polymorphic='*',
    properties={
        'children': relation(
            Node,
            collection_class=ordering_list('position'),
            order_by=[nodes.c.position],
            backref=backref('parent', remote_side=[nodes.c.id]),
            cascade='all',
            ),
        },
    )

mapper(Content, contents, inherits=Node, polymorphic_identity='content')
       
mapper(Document, documents, inherits=Content, polymorphic_identity='document')

class Settings(object):
    def __init__(self, data):
        self.data = data

    def copy(self, newdata):
        data = self.data.copy()
        data.update(newdata)
        copy = self.__class__(data)
        return copy

settings = Table('settings', metadata,
    Column('id', Integer, primary_key=True),
    Column('data', JsonType()),
    )

mapper(Settings, settings)

def get_root(request=None):
    session = DBSession()
    return session.query(Node).filter(Node.parent_id==None).first()

def populate():
    session = DBSession()
    nodecount = session.query(Node).count()
    if nodecount == 0:
        root = Document(name=u"", parent=None, title=u"My Site")
        root.__acl__ = SITE_ACL
        session.add(root)

    settingscount = session.query(Settings).count()
    if settingscount == 0:
        settings = Settings(data={'kotti.db_version': get_version()})
        session.add(settings)

    principals = get_principals()
    if u'admin' not in principals:
        principals[u'admin'] = {
            'name': u'admin',
            'password': get_settings()['kotti.secret'],
            'title': u"Administrator",
            'groups': [u'role:admin'],
            }

    session.flush()
    transaction.commit()

_session = []
def initialize_sql(engine):
    if _session:
        return _session[0]
    DBSession.configure(bind=engine)
    metadata.bind = engine
    metadata.create_all(engine)
    for populate in get_settings()['kotti.populators']:
        populate()
    session = DBSession()
    _session.append(session)
    return session

def appmaker(engine):
    initialize_sql(engine)
    return get_root
