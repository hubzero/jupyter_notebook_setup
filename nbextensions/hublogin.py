import os
import glob
import binascii
from importlib.metadata import version

# With Notebook 7, nbclassic's import shims still answer `import notebook.base.handlers`, so check the
# version rather than whether the import works.
if int(version('notebook').split('.')[0]) < 7:
    from notebook.base.handlers import IPythonHandler, AuthenticatedHandler
    from notebook.utils import url_unescape, url_escape
else:
    # Notebook 7 has no server of its own; nbclassic and JupyterLab run on jupyter_server.  Its
    # LegacyIdentityProvider also calls get_login_available, should_check_origin and
    # is_token_authenticated on the login handler class, which LegacyLoginHandler provides.
    from jupyter_server.auth.login import LegacyLoginHandler as IPythonHandler
    from jupyter_server.base.handlers import AuthenticatedHandler
    from jupyter_server.utils import url_unescape, url_escape

"""
Basic authentication using a cookie set by the hub when the jupyter
server is launched.  When reconnecting from another browser, it will
necessary to go through the hub, otherwise there will be no cookie.
"""


class HubLoginHandler(IPythonHandler):
    cookie_name = None
    session = None
    vncpass = None
    host = None
    first_login = True

    def _render(self, message=None):
        self.write("Access Forbidden")

    def get(self):
        # Called when the current user cannot be authenticated.
        self._render()
    
    @classmethod
    def get_user_token(cls, handler):
        """Identify the user based on a token in the URL
        Returns:
        - token if authenticated
        - None if not
        """
        token = handler.token
        if not token:
            return None
        # check login token from URL argument
        user_token = handler.get_argument('token', '')
        # print("token='%s'   user_token='%s'" % (token, user_token))
        if user_token == token:
            handler.log.debug("Accepting token-authenticated connection from %s", handler.request.remote_ip)
            return token
        return None

    @classmethod
    def get_user(cls, handler):
        # Called by handlers.get_current_user for identifying the current user.
        # Returns None on authentication failure.

        # print("HLH: get_user")

        if cls.cookie_name is None:
            cls.load_env()

        if cls.cookie_name:
            cval = handler.get_cookie(cls.cookie_name)
            if cval is not None:
                cval = url_unescape(cval)
                # print("cookie contained '%s'" % cval)

                for item in cval.split(','):
                    session, passwd = item.split(':')
                    if session == cls.session and passwd == cls.vncpass:
                        cls.first_login = False
                        return "OK"

            # No valid cookie, but first browser to connect
            # gets a free one!
            # This allows painless development from a workspace.
            if cls.first_login:
                cls.first_login = False
                val = url_escape("%s:%s" % (cls.session, cls.vncpass))
                handler.set_cookie(cls.cookie_name, val, domain=cls.host, expires_days=7)
                return "OK"
            
            # No valid cookie and not the first login.
            # How about a login token?
            token = cls.get_user_token(handler)
            if token is not None:
                handler.set_cookie(cls.cookie_name, url_escape(token), domain=cls.host, expires_days=7)
                return "OK"
            
        return None

    @classmethod
    def validate_security(cls, app, ssl_options=None):
        if not app.ip:
            warning = "WARNING: The notebook server is listening on all IP addresses"
            if ssl_options is None:
                app.log.warning(warning + " and not using encryption. This "
                    "is not recommended.")
            if not app.password:
                app.log.warning(warning + " and not using authentication. "
                    "This is highly insecure and not recommended.")

    @classmethod
    def load_env(cls):
        # print("HLH: load_env")
        try:
            cls.session = os.environ['SESSION']

            pwfile = glob.glob('/var/run/Xvnc/passwd-*')[0]
            with open(pwfile, 'rb') as f:
                cls.vncpass = str(binascii.hexlify(f.read()).decode('utf-8'))

            fn = os.path.join(os.environ['SESSIONDIR'], 'resources')
            with open(fn, 'r') as f:
                res = f.read()
            for line in res.split('\n'):
                if line.startswith('hub_url'):
                    url = line.split()[1]
                    cls.host = url[url.find('//')+2:]
                    cls.cookie_name = 'weber-auth-' + cls.host.replace('.','-')
                    break
        except:
            # something very wrong with resources file?
            print("COOKIE FAIL")

# These are used when we want a login/logout button in the UI
# We never want that, so force to off.
def logged_in(self):
    return False

def login_available(self):
    return False

AuthenticatedHandler.logged_in = property(logged_in)
AuthenticatedHandler.login_available = property(login_available)
