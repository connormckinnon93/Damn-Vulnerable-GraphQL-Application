import graphene
import werkzeug

from werkzeug.exceptions import HTTPException


from flask import (
  Flask,
  request,
  jsonify,
  render_template,
  redirect,
  make_response,
  session
)

from flask_graphql import GraphQLView

from graphene_sqlalchemy import (
  SQLAlchemyObjectType,
  SQLAlchemyConnectionField
)

from app import app, db

from core import security
from core import helpers
from core.models import Owner, Paste, User

from version import VERSION


# Middleware
class processMiddleware(object):
  def resolve(self, next, root, info, **kwargs):
    if helpers.is_level_hard():
      array_qry = []

      if info.context.json is not None:
        if isinstance(info.context.json, dict):
          array_qry.append(info.context.json)

        for q in array_qry:
          query = q.get('query', None)
          if security.on_denylist(query):
            raise werkzeug.exceptions.SecurityError('Query is on the deny list.')
    return next(root, info, **kwargs)

class IntrospectionMiddleware(object):
  def resolve(self, next, root, info, **kwargs):
    if helpers.is_level_hard():
      if info.field_name.lower() in ['__schema', '__introspection']:
        raise werkzeug.exceptions.SecurityError('Introspection is Disabled')

    return next(root, info, **kwargs)

class IGQLProtectionMiddleware(object):
  def resolve(self, next, root, info, **kwargs):
    if helpers.is_level_easy():
      cookie = request.cookies.get('env')
      if cookie and helpers.decode_base64(cookie) == 'graphiql:enable':
        return next(root, info, **kwargs)
      else:
        raise werkzeug.exceptions.SecurityError('GraphiQL Access Rejected')

    raise werkzeug.exceptions.SecurityError('GraphiQL is disabled')

  def to_dict(self):
    return {
      "id": self.id,
      "title": self.title,
      "content": self.content,
      "public": self.public,
      "owner":self.owner,
      "burn":self.burn
    }

# SQLAlchemy Types
class UserObject(SQLAlchemyObjectType):
  class Meta:
    model = User
    interfaces = (graphene.relay.Node, )

class PasteObject(SQLAlchemyObjectType):
  p_id = graphene.String(source='id')
  class Meta:
    model = Paste
    interfaces = (graphene.relay.Node, )

class OwnerObject(SQLAlchemyObjectType):
  class Meta:
    model = Owner
    interfaces = (graphene.relay.Node, )


class CreatePaste(graphene.Mutation):
    title = graphene.String()
    content = graphene.String()
    public = graphene.Boolean()
    paste = graphene.Field(lambda:PasteObject)
    burn = graphene.Boolean()

    class Arguments:
      title = graphene.String()
      content = graphene.String()
      public = graphene.Boolean(required=False, default_value=True)
      burn = graphene.Boolean(required=False, default_value=False)

    def mutate(self, info, title, content, public, burn):
      owner = Owner.query.filter_by(name='DVGAUser').first()
      paste_obj = Paste.create_paste(title=title, content=content, public=public, burn=burn,
                         owner_id=owner.id, owner=owner, ip_addr=request.remote_addr,
                         user_agent=request.headers.get('User-Agent', ''))


      return CreatePaste(paste=paste_obj)

class DeletePaste(graphene.Mutation):
  ok = graphene.Boolean()

  class Arguments:
    title = graphene.String()

  def mutate(self, info, title):
    Paste.query.filter_by(title=title).delete()
    db.session.commit()

    return DeletePaste(ok=True)

class UploadPaste(graphene.Mutation):
  content = graphene.String()
  filename = graphene.String()

  class Arguments:
    content = graphene.String(required=True)
    filename = graphene.String(required=True)

  result = graphene.String()

  def mutate(self, info, filename, content):
    result = helpers.save_file(filename, content)
    owner = Owner.query.filter_by(name='DVGAUser').first()
    paste_obj = Paste.create_paste(
      title='Imported Paste from File - {}'.format(helpers.generate_uuid()),
      content=content, public=False, burn=False,
      owner_id=owner.id, owner=owner, ip_addr=request.remote_addr,
      user_agent=request.headers.get('User-Agent', '')
    )

    return UploadPaste(result=result)

class ImportPaste(graphene.Mutation):
  result = graphene.String()

  class Arguments:
    host = graphene.String(required=True)
    port = graphene.Int(required=False)
    path = graphene.String(required=True)
    scheme = graphene.String(required=True)

  def mutate(self, info, host='pastebin.com', port=443, path='/', scheme="http"):
    url = security.strip_dangerous_characters(f"{scheme}://{host}:{port}{path}")
    cmd = helpers.run_cmd(f'curl --insecure {url}')

    owner = Owner.query.filter_by(name='DVGAUser').first()
    paste_obj = Paste.create_paste(
        title='Imported Paste from URL - {}'.format(helpers.generate_uuid()),
        content=cmd, public=False, burn=False,
        owner_id=owner.id, owner=owner, ip_addr=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )

    return ImportPaste(result=cmd)

class Mutations(graphene.ObjectType):
  create_paste = CreatePaste.Field()
  delete_paste = DeletePaste.Field()
  upload_paste = UploadPaste.Field()
  import_paste = ImportPaste.Field()

class Query(graphene.ObjectType):
  node = graphene.relay.Node.Field()
  pastes = graphene.List(PasteObject, public=graphene.Boolean())
  paste = graphene.Field(PasteObject, p_id=graphene.String())
  system_update = graphene.String()
  system_diagnostics = graphene.String(username=graphene.String(), password=graphene.String(), cmd=graphene.String())
  system_health = graphene.String()
  read_and_burn = graphene.Field(PasteObject, p_id=graphene.Int())

  def resolve_pastes(self, info, public=False):
    query = PasteObject.get_query(info)
    return query.filter_by(public=public, burn=False).order_by(Paste.id.desc())

  def resolve_paste(self, info, p_id):
    query = PasteObject.get_query(info)
    return query.filter_by(id=p_id, burn=False).first()

  def resolve_system_update(self, info):
    security.simulate_load()
    return 'no updates available'

  def resolve_system_diagnostics(self, info, username, password, cmd='whoami'):
    q = User.query.filter_by(username='admin').first()
    real_passw = q.password
    res, msg = security.check_creds(username, password, real_passw)
    if res:
      output = f'{cmd}: command not found'
      if security.allowed_cmds(cmd):
        output = helpers.run_cmd(cmd)
      return output
    return msg

  def resolve_read_and_burn(self, info, p_id):
    result = Paste.query.filter_by(id=p_id, burn=True).first()
    Paste.query.filter_by(id=p_id, burn=True).delete()
    db.session.commit()
    return result

  def resolve_system_health(self, info):
    return 'System Load: {}'.format(helpers.run_cmd("uptime | awk -F'averages: ' '{print $2}'"))


@app.route('/')
def index():
  resp = make_response(render_template('index.html'))
  resp.set_cookie("env", "Z3JhcGhpcWw6ZGlzYWJsZQ==")
  return resp

@app.route('/about')
def about():
  return render_template("about.html")

@app.route('/solutions')
def solutions():
  return render_template("solutions.html")

@app.route('/create_paste')
def create_paste():
  return render_template("paste.html", page="create_paste")

@app.route('/import_paste')
def import_paste():
  return render_template("paste.html", page="import_paste")

@app.route('/upload_paste')
def upload_paste():
  return render_template("paste.html", page="upload_paste")

@app.route('/my_pastes')
def my_paste():
  return render_template("paste.html", page="my_pastes")

@app.route('/public_pastes')
def public_paste():
  return render_template("paste.html", page="public_pastes")

@app.route('/start_over')
def start_over():
  msg = "Restored to default state."
  res = helpers.initialize()

  if 'done' not in res:
    msg="Could not restore to default state."

  return render_template('index.html', msg=msg)

@app.route('/difficulty/<level>')
def difficulty(level):
  if level in ('easy', 'hard'):
    message = f'Changed difficulty level to {level.capitalize()}'
  else:
    message = 'Level must be Beginner or Expert.'
    level = 'easy'

  session['difficulty'] = level

  return render_template('index.html', msg = message)


@app.context_processor
def get_version():
  return dict(version=VERSION)

@app.before_request
def set_difficulty():
  mode_header = request.headers.get('X-DVGA-MODE', None)
  if mode_header:
    if mode_header == 'Beginner':
      helpers.set_mode('easy')
    else:
      helpers.set_mode('hard')
  else:
    if session.get('difficulty') == None:
      if request.endpoint == 'index':
        helpers.set_mode('easy')
      else:
        helpers.set_mode('hard')

schema = graphene.Schema(query=Query, mutation = Mutations)

app.add_url_rule('/graphql', view_func=GraphQLView.as_view(
  'graphql',
  schema=schema,
  middleware=[IntrospectionMiddleware(), processMiddleware()],
  batch=True
))

app.add_url_rule('/graphiql', view_func=GraphQLView.as_view(
  'graphiql',
  schema=schema,
  graphiql=True,
  middleware=[IGQLProtectionMiddleware()],
  batch=True
))


