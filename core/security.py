import random
import time

from core import helpers

def simulate_load():
  loads = [200, 300, 400, 500]
  count = 0
  limit = random.choice(loads)
  while True:
    time.sleep(0.1)
    count += 1
    if count > limit:
      return


def is_port(port):
  if isinstance(port, int):
    if port >= 0 and port <= 65535:
      return True
  return False

def allowed_cmds(cmd):
  if helpers.is_level_easy():
    return True
  elif helpers.is_level_hard():
    if cmd.startswith(('echo', 'ps' 'whoami', 'tail')):
      return True
  return False

def strip_dangerous_characters(cmd):
  if helpers.is_level_easy():
    return cmd
  elif helpers.is_level_hard():
    return cmd.replace(';','').replace('&', '')
  return cmd

def check_creds(username, password, real_password):
  if username != 'admin':
    return (False, 'Username is invalid')

  if password == real_password:
    return (True, 'Password Accepted.')

  return (False, 'Password Incorrect')

def on_denylist(query):
  normalized_query = ''.join(query.split())
  queries = [
    'query{systemHealth}',
    '{systemHealth}'
  ]

  if normalized_query in queries:
    return True
  return False

